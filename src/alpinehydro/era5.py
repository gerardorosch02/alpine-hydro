"""Daily mean 2 m air temperature at each lake from ERA5-Land, for the lake-ice test.

Point values from ECMWF/ERA5_LAND/DAILY_AGGR (band temperature_2m, kelvin) at the
centroid of the full-supply outline, fetched once with getRegion and cached in
data/interim/era5/ (git-ignored). ERA5-Land is a 0.1 degree reanalysis, so the cell height
can differ from the lake height; the test only counts frost days, it does not model ice.

Credit: Contains modified Copernicus Climate Change Service information (ERA5-Land).
"""

from __future__ import annotations

import pandas as pd

from alpinehydro import config, outlines

ERA5_DIR = config.INTERIM / "era5"
COLLECTION = "ECMWF/ERA5_LAND/DAILY_AGGR"
CREDIT = "Contains modified Copernicus Climate Change Service information (ERA5-Land)"


def lake_point(slug: str) -> tuple[float, float]:
    """(lon, lat) of the outline centroid, or a point inside it if the centroid is not."""
    lake = outlines.load(slug, "outline")
    p = lake.centroid if lake.contains(lake.centroid) else lake.representative_point()
    q = outlines.transform(outlines.to_wgs84, p)
    return float(q.x), float(q.y)


def fetch(slug: str, start: str = "2012-12-01", refresh: bool = False) -> pd.Series:
    """Daily mean temperature (C) at the lake, indexed by date."""
    path = ERA5_DIR / f"{slug}.csv"
    if path.exists() and not refresh:
        s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["t2m_c"]
        return s
    import ee

    from alpinehydro import water_mask
    from alpinehydro.earthengine import init

    init()
    ee.data.setWorkloadTag(water_mask.WORKLOAD_TAG)
    lon, lat = lake_point(slug)
    end = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    col = ee.ImageCollection(COLLECTION).filterDate(start, end).select("temperature_2m")
    rows = col.getRegion(ee.Geometry.Point(lon, lat), 11132).getInfo()
    df = pd.DataFrame(rows[1:], columns=rows[0]).dropna(subset=["temperature_2m"])
    df["date"] = pd.to_datetime(df["time"], unit="ms").dt.normalize()
    df["t2m_c"] = (df["temperature_2m"] - 273.15).round(2)
    out = df.groupby("date")["t2m_c"].mean().sort_index()
    if out.empty:
        raise RuntimeError(f"ERA5-Land has no value at the {slug} point ({lon:.4f}, {lat:.4f})")
    ERA5_DIR.mkdir(parents=True, exist_ok=True)
    out.reset_index().to_csv(path, index=False, lineterminator="\n")
    return out


def frost_days(t2m: pd.Series, dates: pd.Series, window: int = 30) -> pd.Series:
    """Days below 0 C in the `window` days before each date (the scene day excluded).

    Days missing from the series count as not frosty, so a short record never adds ice.
    """
    cold = (t2m < 0).astype(int)
    cum = cold.cumsum()
    day = pd.to_datetime(dates).dt.tz_localize(None).dt.normalize()

    def upto(d):
        i = cum.index.searchsorted(d, side="left") - 1
        return int(cum.iloc[i]) if i >= 0 else 0

    return pd.Series(
        [upto(d) - upto(d - pd.Timedelta(days=window)) for d in day], index=dates.index
    )
