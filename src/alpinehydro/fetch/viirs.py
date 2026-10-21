"""NOAA-21 VIIRS daily snow cover (NSIDC VJ210A1 v2) for the MODIS fallback.

One granule per day covers Switzerland (sinusoidal tile h18v04, 375 m, 3000 x 3000).
Each granule is downloaded with earthaccess (free Earthdata login: EARTHDATA_USERNAME and
EARTHDATA_PASSWORD in .env), cropped to the box around the three cantons, and only the
cropped NDSI_Snow_Cover array is kept in data/interim/viirs/ (compressed). The granule is
deleted straight away. The daily regional series is built with the same rules as MODIS
(alpinehydro.fallback).

Credit: Riggs, G. A., D. K. Hall and M. O. Roman. VIIRS/NOAA-21 Snow Cover Daily L3
Global 375m SIN Grid, Version 2 (VJ210A1). NASA National Snow and Ice Data Center DAAC.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config, fallback

SHORT_NAME = "VJ210A1"
VERSION = "2"
TILE = "h18v04"
CREDIT = (
    "Riggs, G. A., D. K. Hall and M. O. Roman. VIIRS/NOAA-21 Snow Cover Daily L3 Global "
    "375m SIN Grid, Version 2 (VJ210A1). NASA National Snow and Ice Data Center DAAC."
)
CRS = "+proj=sinu +R=6371007.181 +lon_0=0 +x_0=0 +y_0=0 +units=m +no_defs"
UL_X, UL_Y = 0.0, 5559752.598333
PIXEL = 1111950.519667 / 3000
FIELD = "HDFEOS/GRIDS/VIIRS_Grid_IMG_2D/Data Fields/NDSI_Snow_Cover"
BBOX = (6.7, 45.8, 10.6, 47.1)  # lon/lat box around the three cantons
RAW = config.RAW / "viirs"
CACHE = config.INTERIM / "viirs"
OUT = config.PROCESSED / "snow" / "viirs_vj210a1_daily.csv"


def _window() -> tuple[int, int, int, int]:
    """Row and column range of the tile that holds the box around the three cantons."""
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    lons = [BBOX[0], BBOX[2], BBOX[0], BBOX[2]]
    lats = [BBOX[1], BBOX[1], BBOX[3], BBOX[3]]
    xs, ys = t.transform(lons, lats)
    c0, c1 = int((min(xs) - UL_X) / PIXEL) - 2, int((max(xs) - UL_X) / PIXEL) + 3
    r0, r1 = int((UL_Y - max(ys)) / PIXEL) - 2, int((UL_Y - min(ys)) / PIXEL) + 3
    return r0, r1, c0, c1


def grid():
    """Affine transform and shape of the cropped window."""
    from rasterio.transform import from_origin

    r0, r1, c0, c1 = _window()
    return from_origin(UL_X + c0 * PIXEL, UL_Y - r0 * PIXEL, PIXEL, PIXEL), (r1 - r0, c1 - c0)


def _login():
    import earthaccess

    config._load_env()
    for name in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
        config.secret(name)  # fails without revealing anything if a name is missing
    return earthaccess.login(strategy="environment")


def search(start: str, end: str) -> list:
    import earthaccess

    return earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        temporal=(start, end),
        bounding_box=(7.5, 46.5, 7.6, 46.6),
    )


def _day(g) -> pd.Timestamp:
    return pd.Timestamp(g["umm"]["TemporalExtent"]["RangeDateTime"]["EndingDateTime"][:10])


def publication_lag_days(days_back: int = 30, today: pd.Timestamp | None = None) -> dict:
    """Median and 90th percentile of (first CMR insert minus end of the acquisition day)."""
    _login()
    today = today or pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    gs = search(
        (today - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    )
    lags = []
    for g in gs:
        end = pd.Timestamp(g["umm"]["TemporalExtent"]["RangeDateTime"]["EndingDateTime"])
        ins = [d["Date"] for d in g["umm"].get("ProviderDates", []) if d["Type"] == "Insert"]
        if ins:
            lags.append((pd.Timestamp(ins[0]) - end).total_seconds() / 86400)
    lags = np.array(lags)
    return {
        "granules": len(lags),
        "median_days": round(float(np.median(lags)), 2) if len(lags) else None,
        "p90_days": round(float(np.quantile(lags, 0.9)), 2) if len(lags) else None,
        "window": f"last {days_back} days to {today.date()}",
    }


def fetch(start: str, end: str, log=print) -> int:
    """Download, crop and cache every granule from start to end (inclusive). Resumable."""
    import earthaccess
    import h5py

    _login()
    CACHE.mkdir(parents=True, exist_ok=True)
    r0, r1, c0, c1 = _window()
    todo = [g for g in search(start, end) if not (CACHE / f"{_day(g):%Y-%m-%d}.npz").exists()]
    tmp = RAW / "tmp"
    for i, g in enumerate(todo):
        tmp.mkdir(parents=True, exist_ok=True)
        files = [Path(f) for f in earthaccess.download([g], str(tmp), show_progress=False)]
        h5 = next(f for f in files if f.suffix == ".h5")
        with h5py.File(h5, "r") as h:
            crop = h[FIELD][r0:r1, c0:c1]
        np.savez_compressed(CACHE / f"{_day(g):%Y-%m-%d}.npz", ndsi=crop)
        shutil.rmtree(tmp)
        if i % 20 == 0:
            log(f"VJ210A1 {_day(g).date()} ({i + 1} of {len(todo)})")
    return len(todo)


def load_day(day: pd.Timestamp) -> np.ndarray | None:
    path = CACHE / f"{day:%Y-%m-%d}.npz"
    if not path.exists():
        return None
    return fallback.fsc_from_ndsi(np.load(path)["ndsi"])


def series(start: str, end: str) -> pd.DataFrame:
    """Daily regional FSC from the cache; starts 8 days early so the gap fill is warm."""
    transform, shape = grid()
    masks = fallback.band_masks(transform, shape, CRS)
    days = list(pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=8), end, freq="D"))
    df = fallback.daily_series(days, load_day, masks)
    return df[pd.to_datetime(df["date"]) >= pd.Timestamp(start)].reset_index(drop=True)


def write(df: pd.DataFrame, path: Path = OUT) -> Path:
    header = [
        f"# {CREDIT}",
        "# Derived daily regional values only (no imagery). fsc: FSC = -0.01 + 1.45 NDSI from",
        "# NDSI_Snow_Cover, mean over valid pixels inside the MODIS 1800 m band polygons",
        "# (pixel centres); 8-day per-pixel gap fill; missing: valid share below 0.70.",
        "# MODIS fallback only (weekend 5); never used in any H3 test.",
    ]
    out = df.copy()
    text = "\n".join(header) + "\n" + out.to_csv(index=False, lineterminator="\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path
