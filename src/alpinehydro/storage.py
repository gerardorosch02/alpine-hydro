"""Water level, volume and fill per scene, from the water mask and the hybrid terrain.

Two independent levels per scene:
- level_iou: the h whose "connected terrain at or below h" best matches the water mask
  (intersection over union), ignoring shadow and cloud pixels.
- level_shoreline: the median terrain height along the observed shoreline inside the
  full-supply lake (water pixels next to dry land and dry pixels next to water, both clear
  and lit, away from the dams).
If they differ by more than 3 m the scene is flagged no_match.

If the water area is smaller than the area at the lowest measured level, the level is
read from the fitted A(h) instead (method "area, fitted curve") and the scene is flagged
below_floor. Volume comes from the curve V(h); fill = max(V - dead, 0) / usable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config, hypsometry, water_mask

OUT = config.PROCESSED / "satellite"
CREDITS = [
    "Contains modified Copernicus Sentinel data {years}",
    "Landsat courtesy of the U.S. Geological Survey",
    "Source: Federal Office of Topography swisstopo",
    "Terrain below the swissALTI3D floor: SRTM (NASA/USGS, public domain) or Copernicus "
    "DEM GLO-30 (produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) "
    "Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European "
    "Union and ESA), see data/processed/hypsometry/",
]


def iou_level(join: np.ndarray, water: np.ndarray, valid: np.ndarray, levels: np.ndarray):
    """Return (best level, best IoU) of connected terrain <= h against the water mask."""
    jv = join[valid]
    wv = water[valid]
    pred_sorted = np.sort(jv)
    inter_sorted = np.sort(jv[wv])
    pred = np.searchsorted(pred_sorted, levels, side="right")
    inter = np.searchsorted(inter_sorted, levels, side="right")
    union = pred + wv.sum() - inter
    iou = np.divide(inter, union, out=np.zeros(len(levels)), where=union > 0)
    k = int(np.argmax(iou))
    return float(levels[k]), float(iou[k])


def shoreline_level(z: np.ndarray, lake_water: np.ndarray, valid: np.ndarray, keep: np.ndarray):
    """Median terrain height on both sides of the observed shoreline (NaN if too few).

    lake_water: water pixels inside the full-supply lake (bridges can split the lake, so
    this is not just the largest water body).
    """
    from scipy.ndimage import binary_dilation

    cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    wet_edge = lake_water & binary_dilation(~lake_water & valid, cross)
    dry_edge = ~lake_water & valid & binary_dilation(lake_water, cross)
    sel = (wet_edge | dry_edge) & keep & np.isfinite(z)
    if sel.sum() < 20:
        return float("nan")
    return float(np.median(z[sel]))


def lake_water_area(lake_water: np.ndarray) -> float:
    """Area (km2) of water inside the full-supply lake."""
    return float(lake_water.sum() * hypsometry.RES**2 / 1e6)


def level_from_area(curve: pd.DataFrame, area_km2: float) -> float:
    return float(np.interp(area_km2, curve["area_km2"], curve["level_m"]))


def scene_rows(slug: str) -> pd.DataFrame:
    r = hypsometry.reservoir(slug)
    s = config.pipeline()["satellite"]
    fsl = float(r["full_level_m"])
    g = hypsometry.load_grid(slug)
    hyb = np.load(hypsometry.hybrid_path(slug))
    join, z = hyb["join"], hyb["z"]
    curve = hypsometry.load_curve(slug)
    measured = curve[curve["source"] != "fitted, not measured"]
    levels = measured["level_m"].to_numpy()
    a_lowest = float(measured["area_km2"].iloc[0])
    usable = float(r["usable_volume_mm3"])
    dead = float(r["gross_volume_mm3"]) - usable
    lake_max = join <= fsl
    keep = ~g.near_dam & g.window
    cands = water_mask.candidates(slug)
    rows = []
    for c in cands.itertuples():
        path = water_mask.mask_path(slug, c.sensor, c.date)
        base = {
            "reservoir": slug,
            "sensor": c.sensor,
            "scene_id": c.scene_id,
            "time_utc": pd.Timestamp(c.time_utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clear_fraction": round(float(c.clear_fraction), 4),
        }
        if not path.exists():
            if c.clear_fraction < s["min_clear_fraction"]:
                rows.append({**base, "flag": "cloud"})
            continue
        m = water_mask.classify(water_mask.load_arrays(path), g.window, lake_max)
        flags = list(m["flags"])
        valid = g.window & ~m["shadow"] & ~m["cloud"]
        lake_water = m["water"] & lake_max
        area = lake_water_area(lake_water)
        lvl_iou, iou = iou_level(join, m["water"], valid, levels)
        lvl_shore = shoreline_level(z, lake_water, valid, keep)
        if area < a_lowest:
            level = level_from_area(curve, area)
            method = "area, fitted curve"
            flags.append("below_floor")
        else:
            level = lvl_iou
            method = "iou"
            if not np.isfinite(lvl_shore) or abs(lvl_iou - lvl_shore) > s["no_match_m"]:
                flags.append("no_match")
        volume = float(np.interp(level, curve["level_m"], curve["volume_mm3"]))
        rows.append(
            {
                **base,
                "flag": ";".join(flags) or "ok",
                "threshold": m["threshold"],
                "water_area_km2": round(area, 4),
                "iou": round(iou, 4),
                "level_iou_m": round(lvl_iou, 2),
                "level_shoreline_m": round(lvl_shore, 2) if np.isfinite(lvl_shore) else None,
                "level_m": round(level, 2),
                "method": method,
                "volume_mm3": round(volume, 3),
                "fill": round(max(volume - dead, 0.0) / usable, 4),
                "snow_ice_share": m["snow_ice_share"],
                "shadow_share": m["shadow_share"],
            }
        )
    return pd.DataFrame(rows)


def credit_lines(df: pd.DataFrame | None = None, time_col: str = "time_utc") -> list[str]:
    """Credit lines; the Sentinel years come from the Sentinel-2 rows of df."""
    years = ""
    if df is not None and len(df):
        t = pd.to_datetime(
            df.loc[df["sensor"] == "s2", time_col], utc=True, format="ISO8601"
        ).dt.year
        if len(t):
            years = f"{t.min()}-{t.max()}"
    return [c.format(years=years).rstrip() for c in CREDITS]


def build(slug: str) -> pd.DataFrame:
    """Scene table for one reservoir, cached in data/interim/scenes/."""
    df = scene_rows(slug)
    df.to_csv(water_mask.SCENE_DIR / f"{slug}_scenes.csv", index=False, lineterminator="\n")
    return df


def write_scenes() -> Path:
    """Merge every reservoir's scene table into data/processed/satellite/scenes.csv."""
    frames = [pd.read_csv(p) for p in sorted(water_mask.SCENE_DIR.glob("*_scenes.csv"))]
    df = pd.concat(frames, ignore_index=True).sort_values(["reservoir", "time_utc"])
    header = [f"# {c}" for c in credit_lines(df)]
    header += [
        "# One row per scene (sensor family and UTC day). flag 'ok' means usable; other flags:",
        "# cloud, snow_ice, shadow_heavy, fallback_threshold, below_floor, no_match.",
        "# level_m is level_iou_m unless method is 'area, fitted curve' (below_floor).",
        "# fill = max(volume - dead volume, 0) / usable volume (config/reservoirs.yaml).",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "scenes.csv"
    text = "\n".join(header) + "\n" + df.to_csv(index=False, lineterminator="\n")
    path.write_bytes(text.encode("utf-8"))
    return path


def load_scenes() -> pd.DataFrame:
    return pd.read_csv(OUT / "scenes.csv", comment="#", parse_dates=["time_utc"])
