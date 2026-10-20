"""Global DEMs for the band below the swissALTI3D floor (decision of 2026-10-20).

swissALTI3D flattens each lake at the level of its survey date, which for our seven
reservoirs is within 10 m of full supply. Three global DEMs were captured while the
reservoirs were drawn down, so they show exposed bed below that floor:

  srtm   NASA SRTM v3 (USGS/SRTMGL1_003), radar, February 2000
  glo30  Copernicus DEM GLO-30 (COPERNICUS/DEM/GLO30_2024_1), radar, 2011 to 2015
  aw3d30 JAXA ALOS AW3D30 v4.1 (JAXA/ALOS/AW3D30/V4_1), optical, 2006 to 2011

Selection rule (fixed before comparing results):
- A DEM is eligible if its water surface inside the swissTLM3D outline is clearly flat
  and, after the offset correction below, at least 10 m below the swissALTI3D floor.
  "Clearly flat": take the most common 1 m height bin inside the outline, its median as
  the level, and the largest connected patch within 0.5 m of that level; the patch must
  cover at least 5% of the outline.
- On dry land from the swissALTI3D floor up to 30 m above it (outside both flat patches
  and away from the dams), measure offset = mean(DEM - swissALTI3D) and the RMSE after
  removing that offset.
- Pick the eligible DEM with the lowest RMSE. If another is within 0.5 m RMSE of the best
  and one of them is SRTM, pick SRTM. Correct the chosen DEM by its offset.

Each DEM is pulled onto the 10 m UTM 32N grid with ee.data.computePixels, twice: nearest
neighbour (to find the flat surface) and bilinear (as terrain). One small request per
DEM and reservoir; arrays are cached in data/interim/globaldem/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alpinehydro import config

DEM_DIR = config.INTERIM / "globaldem"
DEMS = ("srtm", "glo30", "aw3d30")
MIN_DROP_M = 10.0
BAND_M = 30.0
FLAT_TOL_M = 0.5
MIN_FLAT_SHARE = 0.05
TIE_RMSE_M = 0.5

INFO = {
    "srtm": {
        "label": "SRTM v3 (NASA/USGS), 1 arc-second",
        "credit": "SRTM: NASA/USGS, public domain",
        "caveat": (
            "Radar, flown 11 to 22 February 2000. Banks were snow covered and C-band radar "
            "penetrates dry snow, so heights there may be biased."
        ),
    },
    "glo30": {
        "label": "Copernicus DEM GLO-30 (2024_1 release)",
        "credit": (
            "Copernicus DEM GLO-30: produced using Copernicus WorldDEM-30 "
            "(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, "
            "provided under COPERNICUS by the European Union and ESA; all rights reserved"
        ),
        "caveat": (
            "TanDEM-X radar, mixed acquisition dates 2011 to 2015. Water surfaces were edited "
            "(flattened) in production, so the lake level may not be a real one-date level."
        ),
    },
    "aw3d30": {
        "label": "ALOS World 3D 30 m v4.1 (JAXA)",
        "credit": "AW3D30: (c) JAXA",
        "caveat": (
            "Optical stereo (PRISM), mixed acquisition dates 2006 to 2011. Water and low-"
            "contrast surfaces may be filled or noisy."
        ),
    },
}


def _image(name: str):
    """Return (nearest, bilinear) ee.Image of one DEM, heights in metres."""
    import ee

    if name == "srtm":
        img = ee.Image("USGS/SRTMGL1_003").select("elevation")
        return img, img.resample("bilinear")
    cid, band = {
        "glo30": ("COPERNICUS/DEM/GLO30_2024_1", "DEM"),
        "aw3d30": ("JAXA/ALOS/AW3D30/V4_1", "DSM"),
    }[name]
    col = ee.ImageCollection(cid).select(band)
    # Resample each tile before mosaicking; a mosaic has no native projection to resample.
    return col.mosaic(), col.map(lambda i: i.resample("bilinear")).mosaic()


def fetch(slug: str, shape: tuple[int, int], transform: tuple, refresh: bool = False) -> dict:
    """Return {dem: (nearest, bilinear)} float32 arrays on the reservoir's 10 m grid."""
    import ee

    from alpinehydro.earthengine import init

    path = DEM_DIR / f"{slug}.npz"
    if path.exists() and not refresh:
        d = np.load(path)
        return {n: (d[f"{n}_nn"], d[f"{n}_bl"]) for n in DEMS}
    init()
    a, b, c, d_, e, f = transform
    h, w = shape
    grid = {
        "dimensions": {"width": int(w), "height": int(h)},
        "affineTransform": {
            "scaleX": a,
            "shearX": b,
            "translateX": c,
            "shearY": d_,
            "scaleY": e,
            "translateY": f,
        },
        "crsCode": "EPSG:32632",
    }
    out, arrays = {}, {}
    for name in DEMS:
        nn, bl = _image(name)
        img = ee.Image.cat(nn.toFloat().rename("nn"), bl.toFloat().rename("bl"))
        px = ee.data.computePixels({"expression": img, "fileFormat": "NUMPY_NDARRAY", "grid": grid})
        out[name] = (px["nn"].astype("float32"), px["bl"].astype("float32"))
        arrays[f"{name}_nn"], arrays[f"{name}_bl"] = out[name]
    DEM_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return out


@dataclass
class Candidate:
    name: str
    flat_level: float  # most common height inside the outline, uncorrected
    flat_share: float  # share of the outline covered by the largest flat patch
    flat: np.ndarray  # mask of that patch
    eligible: bool
    reason: str
    offset: float = float("nan")
    rmse: float = float("nan")
    n: int = 0

    def row(self) -> dict:
        return {
            "dem": self.name,
            "flat_level_m": round(self.flat_level, 2),
            "flat_level_corrected_m": round(self.flat_level - self.offset, 2)
            if np.isfinite(self.offset)
            else None,
            "flat_share_of_outline": round(self.flat_share, 3),
            "eligible": self.eligible,
            "reason": self.reason,
            "offset_m": round(self.offset, 2) if np.isfinite(self.offset) else None,
            "rmse_m": round(self.rmse, 2) if np.isfinite(self.rmse) else None,
            "n": self.n,
        }


def flat_surface(nn: np.ndarray, inside: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Most common 1 m height inside the outline and its largest connected flat patch."""
    from scipy.ndimage import label

    vals = nn[inside & np.isfinite(nn)]
    bins = np.round(vals)
    uniq, counts = np.unique(bins, return_counts=True)
    level = float(np.median(vals[bins == uniq[np.argmax(counts)]]))
    near = inside & (np.abs(nn - level) <= FLAT_TOL_M)
    lab, k = label(near)
    if k == 0:
        return level, 0.0, near
    sizes = np.bincount(lab.ravel())[1:]
    flat = lab == (np.argmax(sizes) + 1)
    return level, float(flat.sum() / inside.sum()), flat


def assess(
    name: str,
    nn: np.ndarray,
    bl: np.ndarray,
    z: np.ndarray,
    inside: np.ndarray,
    swiss_flat: np.ndarray,
    near_dam: np.ndarray,
    window: np.ndarray,
    floor: float,
) -> Candidate:
    level, share, flat = flat_surface(nn, inside)
    cand = Candidate(name, level, share, flat, False, "")
    band = (
        window
        & ~swiss_flat
        & ~flat
        & ~near_dam
        & np.isfinite(z)
        & np.isfinite(bl)
        & (z > floor)
        & (z <= floor + BAND_M)
    )
    diff = (bl - z)[band].astype("float64")
    if diff.size:
        cand.offset = float(diff.mean())
        cand.rmse = float(np.sqrt(np.mean((diff - cand.offset) ** 2)))
        cand.n = int(diff.size)
    if share < MIN_FLAT_SHARE:
        cand.reason = f"not clearly flat ({share:.1%} of outline)"
    elif not cand.n:
        cand.reason = "no dry-land pixels to compare"
    elif level - cand.offset > floor - MIN_DROP_M:
        cand.reason = f"flat surface only {floor - (level - cand.offset):.1f} m below the floor"
    else:
        cand.eligible, cand.reason = True, "eligible"
    return cand


def choose(cands: list[Candidate]) -> Candidate | None:
    ok = sorted((c for c in cands if c.eligible and c.n > 0), key=lambda c: c.rmse)
    if not ok:
        return None
    best = ok[0]
    srtm = next((c for c in ok if c.name == "srtm"), None)
    if srtm is not None and srtm.rmse - best.rmse <= TIE_RMSE_M:
        return srtm
    return best
