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
