"""Per-scene water masks from Sentinel-2 and Landsat 8/9, computed in Earth Engine.

Scenes
- Sentinel-2 SR Harmonized from 2017-03-28, clouds from Cloud Score+ (cs_cdf >= 0.6).
- Landsat 8 and 9 Collection 2 Level 2 from 2013, clouds from QA_PIXEL (fill, dilated
  cloud, cirrus, cloud and cloud shadow bits).
- All months for Sihlsee and Gruyere, June to November for the others.
- Images of one sensor family on the same UTC day are one scene (tile overlaps).
- A scene is kept if at least 90% of the 300 m window is clear.

Two passes. `candidates` runs one reduceRegion per scene to get the clear fraction (a
cheap number). `pull` fetches small arrays for the kept scenes with ee.data.computePixels
onto the reservoir's 10 m UTM 32N grid: MNDWI and NIR (x 10000 as int16), clear, and
terrain shadow from ee.Terrain.hillShadow on GLO-30 with the scene's mean sun angles.
Water is classified here, not in Earth Engine:

  water = MNDWI > Otsu threshold (per scene)  and  NIR < 0.12  and  lit  and  clear

If the MNDWI histogram is not two-peaked, the threshold is 0 and the scene is flagged
fallback_threshold. Arrays are cached in data/interim/masks/ (git-ignored).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config, outlines

MASK_DIR = config.INTERIM / "masks"
SCENE_DIR = config.INTERIM / "scenes"
WORKLOAD_TAG = "alpinehydro-weekend2"
FLAGS = ("cloud", "snow_ice", "shadow_heavy", "fallback_threshold")


def settings() -> dict:
    return config.pipeline()["satellite"]


def months(slug: str) -> list[int]:
    s = settings()
    return list(range(1, 13)) if slug in s["all_months"] else list(s["season_months"])


# ---------------------------------------------------------------- Earth Engine side


def _window_ee(slug: str):
    import ee
    from shapely.geometry import mapping

    win = outlines.load(slug, "window")
    return ee.Geometry(mapping(outlines.transform(outlines.to_wgs84, win)))


def _prepare_s2(img):
    """Reflectance bands at 10 m (SWIR1 bilinear), clear mask, sun angles as properties."""
    import ee

    green = img.select("B3").divide(10000)
    nir = img.select("B8").divide(10000)
    swir = img.select("B11").resample("bilinear").divide(10000)
    clear = img.select("cs_cdf").gte(settings()["cs_cdf_min"])
    return ee.Image.cat(
        green.rename("green"), nir.rename("nir"), swir.rename("swir1"), clear.rename("clear")
    ).copyProperties(img, ["system:time_start"])


def _prepare_landsat(img):
    import ee

    def sr(b):
        return img.select(b).multiply(2.75e-05).add(-0.2).resample("bilinear")

    qa = img.select("QA_PIXEL")
    # Bits: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow.
    clear = qa.bitwiseAnd(0b11111).eq(0)
    return ee.Image.cat(
        sr("SR_B3").rename("green"),
        sr("SR_B5").rename("nir"),
        sr("SR_B6").rename("swir1"),
        clear.rename("clear"),
    ).copyProperties(img, ["system:time_start"])


def _collection(slug: str, sensor: str, mlist: list[int] | None = None):
    """Filtered, prepared ee.ImageCollection for one sensor family ('s2' or 'landsat').

    mlist overrides the months of the reservoir (used by one-off checks).
    """
    import ee

    s = settings()
    win = _window_ee(slug)
    mfilter = ee.Filter.Or(
        *[ee.Filter.calendarRange(m, m, "month") for m in (mlist or months(slug))]
    )
    end = dt.date.today().isoformat()
    if sensor == "s2":
        cs = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(win)
            .filterDate(s["s2_start"], end)
            .filter(mfilter)
            .linkCollection(cs, ["cs_cdf"])
        )
        return col, _prepare_s2
    col = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
        .filterBounds(win)
        .filterDate(s["landsat_start"], end)
        .filter(mfilter)
    )
    return col, _prepare_landsat


def scene_list(slug: str, sensor: str, months: list[int] | None = None) -> pd.DataFrame:
    """One row per (sensor family, UTC day): metadata only, no pixels."""
    import ee

    from alpinehydro.earthengine import init

    init()
    col, _ = _collection(slug, sensor, months)
    if sensor == "s2":
        keys = ["system:index", "system:time_start", "SPACECRAFT_NAME"]
        keys += ["MEAN_SOLAR_AZIMUTH_ANGLE", "MEAN_SOLAR_ZENITH_ANGLE"]
    else:
        keys = ["system:index", "system:time_start", "SPACECRAFT_ID"]
        keys += ["SUN_AZIMUTH", "SUN_ELEVATION"]
    info = col.reduceColumns(ee.Reducer.toList(len(keys)), keys).get("list").getInfo()
    df = pd.DataFrame(info, columns=["index", "t", "craft", "sun_az", "sun_x"])
    if sensor == "landsat":
        df["sun_x"] = 90 - df["sun_x"]  # elevation to zenith
    df["time_utc"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["date"] = df["time_utc"].dt.strftime("%Y-%m-%d")
    g = df.sort_values("t").groupby("date")
    out = pd.DataFrame(
        {
            "sensor": sensor,
            "scene_id": g["index"].first().map(lambda i: _scene_id(sensor, i)),
            "time_utc": g["time_utc"].first(),
            "n_images": g.size(),
            "sun_azimuth": g["sun_az"].mean().round(2),
            "sun_zenith": g["sun_x"].mean().round(2),
        }
    ).reset_index()
    return out


def _scene_id(sensor: str, index: str) -> str:
    # Landsat merged collections prefix the index with "1_" or "2_".
    if sensor == "landsat" and index[:2] in ("1_", "2_"):
        index = index[2:]
    return index


def _day_image(slug: str, sensor: str, date: str, months: list[int] | None = None):
    import ee

    col, prep = _collection(slug, sensor, months)
    d0 = ee.Date(date)
    return col.filterDate(d0, d0.advance(1, "day")).map(prep).mosaic()


def clear_fractions(
    slug: str, sensor: str, dates: list[str], chunk: int = 50, months: list[int] | None = None
) -> pd.Series:
    """Share of the window that is clear and covered, per day (one reduceRegion each)."""
    import ee

    from alpinehydro.earthengine import init

    init()
    ee.data.setWorkloadTag(WORKLOAD_TAG)
    win = _window_ee(slug)
    scale = 20 if sensor == "s2" else 30
    out = {}
    for i in range(0, len(dates), chunk):
        part = dates[i : i + chunk]

        def frac(d, win=win, scale=scale):
            img = _day_image(slug, sensor, d, months).select("clear").unmask(0)
            v = img.reduceRegion(ee.Reducer.mean(), win, scale=scale, maxPixels=1e8)
            return v.get("clear")

        vals = ee.List([frac(d) for d in part]).getInfo()
        out.update(dict(zip(part, vals, strict=True)))
    return pd.Series(out, name="clear_fraction")


def candidates(slug: str, refresh: bool = False) -> pd.DataFrame:
    """All scenes with their clear fraction; cached in data/interim/scenes/."""
    path = SCENE_DIR / f"{slug}_candidates.csv"
    if path.exists() and not refresh:
        df = pd.read_csv(path)
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, format="ISO8601")
        return df
    frames = []
    for sensor in ("s2", "landsat"):
        df = scene_list(slug, sensor)
        df["clear_fraction"] = clear_fractions(slug, sensor, df["date"].tolist()).values
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).sort_values("time_utc")
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    return out


def _grid(slug: str) -> dict:
    from alpinehydro import hypsometry

    g = hypsometry.load_grid(slug)
    a, b, c, d, e, f = g.transform
    h, w = g.shape
    return {
        "dimensions": {"width": int(w), "height": int(h)},
        "affineTransform": {
            "scaleX": a,
            "shearX": b,
            "translateX": c,
            "shearY": d,
            "scaleY": e,
            "translateY": f,
        },
        "crsCode": "EPSG:32632",
    }


def mask_path(slug: str, sensor: str, date: str) -> Path:
    return MASK_DIR / slug / f"{sensor}_{date}.npz"


def pull(
    slug: str,
    sensor: str,
    date: str,
    sun_azimuth: float,
    sun_zenith: float,
    months: list[int] | None = None,
) -> Path:
    """Fetch MNDWI, NIR, clear and lit arrays for one scene (cached)."""
    import ee

    from alpinehydro.earthengine import init

    path = mask_path(slug, sensor, date)
    if path.exists():
        return path
    init()
    ee.data.setWorkloadTag(WORKLOAD_TAG)
    img = _day_image(slug, sensor, date, months)
    mndwi = img.normalizedDifference(["green", "swir1"])
    dem_col = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM")
    dem = dem_col.mosaic().setDefaultProjection("EPSG:32632", None, 30)
    lit = ee.Terrain.hillShadow(dem, sun_azimuth, sun_zenith, 200, True)
    stack = ee.Image.cat(
        mndwi.multiply(10000).round().unmask(-32768).toInt16().rename("mndwi"),
        img.select("nir").multiply(10000).round().unmask(-32768).toInt16().rename("nir"),
        img.select("clear").unmask(0).toUint8().rename("clear"),
        lit.unmask(1).toUint8().rename("lit"),
    )
    px = ee.data.computePixels(
        {"expression": stack, "fileFormat": "NUMPY_NDARRAY", "grid": _grid(slug)}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        mndwi=px["mndwi"],
        nir=px["nir"],
        clear=px["clear"].astype(bool),
        lit=px["lit"].astype(bool),
    )
    return path


# ---------------------------------------------------------------- classification


def otsu(values: np.ndarray, bins: int = 200, lo: float = -1.0, hi: float = 1.0) -> float:
    """Otsu threshold of 1-D values: the cut that maximises between-class variance."""
    hist, edges = np.histogram(values, bins=bins, range=(lo, hi))
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centres)
    m0 = np.divide(s0, w0, out=np.zeros_like(s0, dtype=float), where=w0 > 0)
    m1 = np.divide(s0[-1] - s0, w1, out=np.zeros_like(s0, dtype=float), where=w1 > 0)
    between = w0 * w1 * (m0 - m1) ** 2
    # With an empty gap between the classes every cut in the gap ties; take the middle.
    ties = between >= between.max() * (1 - 1e-9)
    return float(edges[1:][ties].mean())


def two_peaked(values: np.ndarray, thr: float, bins: int = 100) -> bool:
    """True if the histogram has a peak on each side of thr and a clear valley between.

    On counts smoothed over 5 bins of 0.02: the smaller peak must hold at least 0.5% of the
    values, and the lowest point between the peaks must be at most half the smaller peak.
    """
    hist, edges = np.histogram(values, bins=bins, range=(-1, 1))
    smooth = np.convolve(hist, np.ones(5) / 5, mode="same")
    centres = (edges[:-1] + edges[1:]) / 2
    left, right = smooth[centres < thr], smooth[centres >= thr]
    if left.size == 0 or right.size == 0:
        return False
    i_l = int(np.argmax(left))
    i_r = int(np.argmax(right)) + left.size
    p_l, p_r = smooth[i_l], smooth[i_r]
    if min(p_l, p_r) < 0.005 * values.size:
        return False
    valley = smooth[i_l : i_r + 1].min()
    return bool(valley <= 0.5 * min(p_l, p_r))


def classify(arrays: dict, window: np.ndarray, lake_max: np.ndarray) -> dict:
    """Water mask and scene flags. lake_max: pixels inside the full-supply lake."""
    s = settings()
    valid = arrays["mndwi"] > -32768
    mndwi = arrays["mndwi"] / 10000.0
    nir = arrays["nir"] / 10000.0
    clear = arrays["clear"] & valid
    lit = arrays["lit"]
    use = window & clear & lit
    vals = mndwi[use]
    flags = []
    clear_frac = float((window & clear).sum() / window.sum())
    if clear_frac < s["min_clear_fraction"]:
        flags.append("cloud")
    thr = otsu(vals) if vals.size > 100 else 0.0
    if vals.size <= 100 or not two_peaked(vals, thr):
        thr = 0.0
        flags.append("fallback_threshold")
    water = (mndwi > thr) & (nir < s["nir_max"]) & lit & clear & window
    shadow = window & ~lit
    lake_n = max(int(lake_max.sum()), 1)
    bright = lake_max & clear & (mndwi > thr) & (nir >= s["nir_max"])
    snow_share = float(bright.sum() / lake_n)
    shadow_share = float((lake_max & ~lit).sum() / lake_n)
    if snow_share > s["snow_ice_share"]:
        flags.append("snow_ice")
    if shadow_share > s["shadow_heavy_share"]:
        flags.append("shadow_heavy")
    return {
        "water": water,
        "shadow": shadow,
        "cloud": window & ~clear,
        "threshold": round(thr, 4),
        "clear_fraction": round(clear_frac, 4),
        "snow_ice_share": round(snow_share, 4),
        "shadow_share": round(shadow_share, 4),
        "flags": flags,
    }


def load_arrays(path: Path) -> dict:
    d = np.load(path)
    return {k: d[k] for k in d.files}


def pull_rgb(slug: str, date: str) -> np.ndarray:
    """True-colour Sentinel-2 crop (B4, B3, B2 reflectance x 10000) on the reservoir grid.

    Only for the example figure; cached in data/interim/masks/ (git-ignored).
    """
    path = MASK_DIR / slug / f"rgb_{date}.npz"
    if path.exists():
        return np.load(path)["rgb"]
    import ee

    from alpinehydro.earthengine import init

    init()
    ee.data.setWorkloadTag(WORKLOAD_TAG)
    win = _window_ee(slug)
    d0 = ee.Date(date)
    img = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(win)
        .filterDate(d0, d0.advance(1, "day"))
        .mosaic()
        .select(["B4", "B3", "B2"])
        .toInt16()
    )
    px = ee.data.computePixels(
        {"expression": img, "fileFormat": "NUMPY_NDARRAY", "grid": _grid(slug)}
    )
    rgb = np.dstack([px["B4"], px["B3"], px["B2"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, rgb=rgb)
    return rgb
