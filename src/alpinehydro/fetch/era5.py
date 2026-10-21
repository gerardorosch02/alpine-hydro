"""Country-mean daily 2 m temperature and heating degree days (H1 controls).

ERA5-Land daily aggregates (ECMWF/ERA5_LAND/DAILY_AGGR, band temperature_2m, kelvin) in
Earth Engine. The country mean is area-weighted over the land grid cells inside the
country outline: sum(T x cell area) / sum(cell area), with ee.Image.pixelArea(). ERA5-Land
is land-only, so sea cells are already masked. Outlines: USDOS/LSIB_SIMPLE/2017.

HDD = max(0, 15.5 - T) per day (base 15.5 C, as pre-registered). The series is cached in
data/interim/era5_country/ (git-ignored).

Credit: Contains modified Copernicus Climate Change Service information (ERA5-Land).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alpinehydro import config

OUT_DIR = config.INTERIM / "era5_country"
COUNTRIES = {"CH": "Switzerland", "DE": "Germany"}
HDD_BASE_C = 15.5
SCALE_M = 11132  # ERA5-Land native 0.1 degree


def _year(country: str, year: int) -> pd.Series:
    import ee

    from alpinehydro.earthengine import init

    init()
    ee.data.setWorkloadTag("alpinehydro-weekend3")
    geom = (
        ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017")
        .filter(ee.Filter.eq("country_na", COUNTRIES[country]))
        .geometry()
    )
    end = min(pd.Timestamp(f"{year + 1}-01-01"), pd.Timestamp.today().normalize())
    col = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(f"{year}-01-01", end.strftime("%Y-%m-%d"))
        .select("temperature_2m")
    )

    def one(img):
        t = img.select("temperature_2m")
        area = ee.Image.pixelArea().updateMask(t.mask())
        s = ee.Image.cat(t.multiply(area).rename("ta"), area.rename("a")).reduceRegion(
            ee.Reducer.sum(), geom, scale=SCALE_M, maxPixels=1e9
        )
        return ee.Feature(
            None, {"t": img.get("system:time_start"), "ta": s.get("ta"), "a": s.get("a")}
        )

    rows = ee.FeatureCollection(col.map(one)).getInfo()["features"]
    df = pd.DataFrame([r["properties"] for r in rows]).dropna()
    day = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    return pd.Series((df["ta"] / df["a"]).to_numpy() - 273.15, index=day, name="t2m_c")


def fetch(country: str, first_year: int = 2004, refresh: bool = False, log=print) -> pd.Series:
    """Daily country-mean temperature (C), cached per year; the current year is refetched."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    this = pd.Timestamp.today().year
    parts = []
    for y in range(first_year, this + 1):
        path = OUT_DIR / f"{country}_{y}.csv"
        if path.exists() and not refresh and y < this:
            s = pd.read_csv(path, parse_dates=["day"]).set_index("day")["t2m_c"]
        else:
            s = _year(country, y).rename_axis("day")
            s.reset_index().to_csv(path, index=False, lineterminator="\n")
            log(f"{country} {y}: {len(s)} days")
        parts.append(s)
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated(keep="first")]


def hdd(country: str) -> pd.Series:
    """Daily heating degree days, base 15.5 C."""
    return (HDD_BASE_C - fetch(country)).clip(lower=0).rename("hdd")


# ---------------------------------------------------------------- CDS route (deviation D15)

CDS_DIR = config.RAW / "cds"
CDS_DATASET = "derived-era5-land-daily-statistics"
BOXES = {"CH": [47.9, 5.9, 45.8, 10.6], "DE": [55.1, 5.8, 47.2, 15.1]}  # N, W, S, E


def outline(country: str) -> dict:
    """The LSIB_SIMPLE/2017 outline used by the Earth Engine route, cached once as GeoJSON."""
    import json

    path = OUT_DIR / f"{country}_lsib_simple_2017.geojson"
    if not path.exists():
        import ee

        from alpinehydro.earthengine import init

        init()
        geom = (
            ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017")
            .filter(ee.Filter.eq("country_na", COUNTRIES[country]))
            .geometry()
            .getInfo()
        )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(geom), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def _cds_month(country: str, year: int, month: int, refresh: bool = False) -> Path:
    import os

    import cdsapi

    path = CDS_DIR / f"{country}_{year}-{month:02d}.nc"
    if path.exists() and not refresh:
        return path
    config.secret("CDSAPI_KEY")  # fails without revealing anything if missing
    c = cdsapi.Client(
        url=os.environ["CDSAPI_URL"], key=os.environ["CDSAPI_KEY"], quiet=True, progress=False
    )
    req = {
        "variable": ["2m_temperature"],
        "year": str(year),
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": BOXES[country],
    }
    CDS_DIR.mkdir(parents=True, exist_ok=True)
    c.retrieve(CDS_DATASET, req).download(str(path))
    return path


def _country_mean(path: Path, country: str) -> pd.Series:
    """Area-weighted mean over land cells whose centre lies inside the outline."""
    import h5py
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import shape

    geom = shape(outline(country))
    with h5py.File(path, "r") as h:
        lat, lon = h["latitude"][:], h["longitude"][:]
        t2m = h["t2m"][:].astype("float64")
        days = h["valid_time"][:]
        units = h["valid_time"].attrs["units"]
    units = units.decode() if isinstance(units, bytes) else units
    base = pd.Timestamp(units.split("since")[1].strip())
    lon2, lat2 = np.meshgrid(lon, lat)
    inside = contains_xy(geom, lon2, lat2)
    w = np.cos(np.deg2rad(lat2)) * inside
    out = {}
    for i, d in enumerate(days):
        v = t2m[i]
        ok = np.isfinite(v) & (w > 0)
        if ok.sum() == 0:
            continue
        out[base + pd.Timedelta(days=float(d))] = float((v[ok] * w[ok]).sum() / w[ok].sum())
    return pd.Series(out, name="t2m_c").sort_index() - 273.15


def fetch_cds(country: str, start: str, end: str | None = None) -> pd.Series:
    """Daily country-mean temperature (C) from the CDS, month by month.

    Months that may still grow (the last 2 months) are always requested again.
    """
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    recent = pd.Timestamp.today().normalize() - pd.DateOffset(months=2)
    parts = []
    for m in pd.date_range(pd.Timestamp(start).replace(day=1), end_ts, freq="MS"):
        path = _cds_month(country, m.year, m.month, refresh=m >= recent.replace(day=1))
        parts.append(_country_mean(path, country))
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated(keep="last")].rename_axis("day")


def hdd_live(country: str, days_back: int = 70) -> pd.Series:
    """HDD for live origins (D15): CDS values for the last `days_back` days, Earth Engine
    history before that (used only for the climatological HDD of past years)."""
    hist = hdd(country)
    start = (pd.Timestamp.today().normalize() - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
    cds = (HDD_BASE_C - fetch_cds(country, start)).clip(lower=0)
    cds = cds[cds.index >= pd.Timestamp(start)]
    return pd.concat([hist[hist.index < pd.Timestamp(start)], cds]).sort_index().rename("hdd")
