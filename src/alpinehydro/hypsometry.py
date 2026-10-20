"""Terrain, surveyed floor and the level-area-volume curve of each reservoir.

Route: swissALTI3D 2 m tiles from the swisstopo STAC API, cached in data/interim/.
The Earth Engine community catalogue has swissSURFACE3D but not swissALTI3D, so the
tiles are downloaded directly. They are mosaicked and averaged onto the Sentinel-2 10 m
grid in UTM 32N (EPSG:32632), and every later step works on that grid.

Inside a lake, swissALTI3D holds a flat water surface at the level of the survey date.
That level is the "floor": below it the bed is unknown.

"Connected terrain at or below h" is computed once per reservoir by flooding outward
from the floor patch: each pixel gets the lowest water level at which it joins the lake
(the lowest possible maximum height along any path from the floor). Near each dam the
path cost uses the 2 m maximum height inside the 10 m pixel, so a thin dam crest still
blocks the flood. A(h) is then the number of pixels that join at or below h.

Hybrid terrain (decision of 2026-10-20): the swissALTI3D floor is within 10 m of full
supply for all seven reservoirs. Inside the swissALTI3D lake, a global DEM captured at a
lower level (see globaldem.py) is used, corrected by its offset against swissALTI3D,
down to that DEM's own flat water surface. Below it, A(h) = c (h - h0)^b is fitted with
b between 1 and 4. The curve has three parts: measured at 2 m (swissALTI3D), measured at
30 m (global DEM), and fitted.
"""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

from alpinehydro import config, outlines

STAC_ITEMS = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissalti3d/items"
TILE_DIR = config.INTERIM / "swissalti3d"
GRID_DIR = config.INTERIM / "terrain"
CURVE_DIR = config.PROCESSED / "hypsometry"
CRS = "EPSG:32632"
RES = 10.0
STEP = 0.25
# Dams here are 520 to 700 m long; 400 m around the dam point covers each crest.
DAM_RADIUS_M = 400.0
# A pixel belongs to the flat floor patch if it is within this height of the floor.
FLAT_TOL_M = 0.05
CREDIT = "Source: Federal Office of Topography swisstopo (swissALTI3D, swissTLM3D)"

to_utm_from_lv95 = Transformer.from_crs(2056, 32632, always_xy=True).transform
to_utm_from_wgs84 = Transformer.from_crs(4326, 32632, always_xy=True).transform


def reservoir(slug: str) -> dict:
    return next(r for r in config.reservoirs() if r["slug"] == slug)


# ---------------------------------------------------------------- tiles


def tile_items(bbox_wgs84: tuple[float, float, float, float]) -> dict[str, tuple[int, str]]:
    """Return {tile key: (survey year, 2 m GeoTIFF url)}, keeping the latest year per tile."""
    url = f"{STAC_ITEMS}?bbox={','.join(f'{v:.5f}' for v in bbox_wgs84)}&limit=100"
    tiles: dict[str, tuple[int, str]] = {}
    while url:
        d = requests.get(url, timeout=60).json()
        for f in d["features"]:
            _, year, key = f["id"].split("_")
            href = next(a["href"] for k, a in f["assets"].items() if k.endswith("_2_2056_5728.tif"))
            if key not in tiles or int(year) > tiles[key][0]:
                tiles[key] = (int(year), href)
        url = next((lk["href"] for lk in d.get("links", []) if lk["rel"] == "next"), None)
    return tiles


def download_tiles(slug: str) -> list[tuple[Path, int]]:
    """Download (or reuse) the 2 m tiles covering the analysis window."""
    win = outlines.load(slug, "window")
    lon0, lat0, lon1, lat1 = outlines.transform(outlines.to_wgs84, win).bounds
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for key, (year, href) in sorted(tile_items((lon0, lat0, lon1, lat1)).items()):
        path = TILE_DIR / f"swissalti3d_{year}_{key}_2.tif"
        if not path.exists():
            r = requests.get(href, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
        out.append((path, year))
    return out


# ---------------------------------------------------------------- 10 m grid


@dataclass
class Grid:
    """Terrain and masks on the 10 m UTM 32N grid of one reservoir."""

    z: np.ndarray  # mean terrain height in the 10 m pixel (NaN where no data)
    zmax: np.ndarray  # maximum 2 m height in the 10 m pixel
    year: np.ndarray  # swissALTI3D survey year of the tile (0 where no data)
    outline: np.ndarray  # inside the swissTLM3D outline
    window: np.ndarray  # inside the 300 m window
    transform: tuple  # affine (a, b, c, d, e, f) of the grid
    near_dam: np.ndarray  # within DAM_RADIUS_M of any dam

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape


def grid_bounds(slug: str) -> tuple[float, float, float, float]:
    """Window bounds in UTM 32N, snapped outward to multiples of 10 m (Sentinel-2 grid)."""
    win = outlines.load(slug, "window")
    x0, y0, x1, y1 = outlines.transform(to_utm_from_lv95, win).bounds
    return (
        np.floor(x0 / RES) * RES,
        np.floor(y0 / RES) * RES,
        np.ceil(x1 / RES) * RES,
        np.ceil(y1 / RES) * RES,
    )


def build_grid(slug: str) -> Grid:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.merge import merge
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    tiles = download_tiles(slug)
    x0, y0, x1, y1 = grid_bounds(slug)
    width, height = int((x1 - x0) / RES), int((y1 - y0) / RES)
    dst_t = from_origin(x0, y1, RES, RES)

    srcs = [rasterio.open(p) for p, _ in tiles]
    mosaic, src_t = merge(srcs, nodata=-9999.0)
    src_crs = srcs[0].crs
    for s in srcs:
        s.close()
    mosaic = mosaic[0].astype("float32")
    mosaic[mosaic <= -9999.0] = np.nan

    def warp(src, resampling):
        dst = np.full((height, width), np.nan, dtype="float32")
        reproject(
            src,
            dst,
            src_transform=src_t,
            src_crs=src_crs,
            dst_transform=dst_t,
            dst_crs=CRS,
            resampling=resampling,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )
        return dst

    z = warp(mosaic, Resampling.average)
    zmax = warp(mosaic, Resampling.max)

    # Survey year raster: one value per 1 km tile, painted from the tile key (LV95 km).
    year = np.zeros((height, width), dtype="int16")
    shapes = []
    for p, yr in tiles:
        e_km, n_km = (int(v) for v in p.stem.split("_")[2].split("-"))
        from shapely.geometry import box

        tile = box(e_km * 1000, n_km * 1000, (e_km + 1) * 1000, (n_km + 1) * 1000)
        shapes.append((outlines.transform(to_utm_from_lv95, tile), yr))
    year = rasterize(shapes, out_shape=(height, width), transform=dst_t, dtype="int16")
    year[np.isnan(z)] = 0

    def paint(geom_lv95):
        g = outlines.transform(to_utm_from_lv95, geom_lv95)
        return rasterize([(g, 1)], out_shape=(height, width), transform=dst_t).astype(bool)

    r = reservoir(slug)
    from shapely.geometry import Point

    dams = [r["dam"], *r.get("other_dams", [])]
    dam_pts = [Point(to_utm_from_wgs84(d["lon"], d["lat"])).buffer(DAM_RADIUS_M) for d in dams]
    near_dam = rasterize(
        [(g, 1) for g in dam_pts], out_shape=(height, width), transform=dst_t
    ).astype(bool)

    return Grid(
        z=z,
        zmax=zmax,
        year=year,
        outline=paint(outlines.load(slug, "outline")),
        window=paint(outlines.load(slug, "window")),
        transform=tuple(dst_t)[:6],
        near_dam=near_dam,
    )


# ---------------------------------------------------------------- floor and flooding


def find_floor(z: np.ndarray, inside: np.ndarray) -> tuple[float, np.ndarray, float]:
    """Find the flat water surface in the terrain model inside the lake outline.

    Returns (floor level, flat-patch mask, share of the outline that is flat).
    The floor is the most common height (to 1 cm) inside the outline.
    """
    vals = z[inside & np.isfinite(z)]
    if vals.size == 0:
        raise ValueError("no terrain data inside the outline")
    cm = np.round(vals * 100).astype(np.int64)
    uniq, counts = np.unique(cm, return_counts=True)
    floor = float(uniq[np.argmax(counts)]) / 100
    flat = inside & (np.abs(z - floor) <= FLAT_TOL_M)
    return floor, flat, float(flat.sum() / inside.sum())


def join_levels(cost: np.ndarray, seed: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """Lowest water level at which each pixel connects to the seed (4-connected flooding).

    cost: height used for passing a pixel. Pixels outside `allowed` or with NaN cost
    never join (inf). Seed pixels join at their own cost.
    """
    h, w = cost.shape
    out = np.full((h, w), np.inf)
    ok = allowed & np.isfinite(cost)
    heap: list[tuple[float, int, int]] = []
    for i, j in zip(*np.nonzero(seed & ok), strict=True):
        out[i, j] = cost[i, j]
        heap.append((float(cost[i, j]), int(i), int(j)))
    heapq.heapify(heap)
    while heap:
        lvl, i, j = heapq.heappop(heap)
        if lvl > out[i, j]:
            continue
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < h and 0 <= b < w and ok[a, b]:
                nl = max(lvl, float(cost[a, b]))
                if nl < out[a, b]:
                    out[a, b] = nl
                    heapq.heappush(heap, (nl, a, b))
    return out


def level_area(
    join: np.ndarray, levels: np.ndarray, pixel_area_m2: float = RES * RES
) -> np.ndarray:
    """A(h) in km2 for each level: pixels that join the lake at or below h."""
    finite = np.sort(join[np.isfinite(join)].ravel())
    return np.searchsorted(finite, levels, side="right") * pixel_area_m2 / 1e6


# ---------------------------------------------------------------- curve below the floor


@dataclass
class PowerFit:
    h0: float
    b: float
    c: float
    method: str

    def area(self, h: np.ndarray) -> np.ndarray:
        return self.c * np.clip(h - self.h0, 0, None) ** self.b

    def volume(self, h: np.ndarray) -> np.ndarray:
        """Integral of A from h0 to h, in the units of c (km2 x m = Mm3)."""
        return self.c * np.clip(h - self.h0, 0, None) ** (self.b + 1) / (self.b + 1)


B_MIN, B_MAX = 1.0, 4.0


def slope_join_b(a_floor: float, v_below: float, slope: float) -> float:
    """b from a smooth join (dA/dh at the floor = slope). Recorded as a check only."""
    k = slope * v_below / a_floor**2
    return k / (1 - k) if 0 < k < 1 else (np.inf if k >= 1 else 0.0)


def fit_below_floor(a_floor: float, v_below: float, floor: float, bed: float) -> PowerFit:
    """Fit A(h) = c (h - h0)^b below the lowest measured level ("floor" here).

    Constraints: A(floor) = a_floor, the integral from h0 to the floor = v_below, and
    h0 = the published bed level. b is bounded to [1, 4]. If the bed gives a b outside the
    bounds, b is set to the bound and h0 moves so that area and volume still hold; method
    says so. Units: km2, m, Mm3.
    """
    if v_below <= 0 or a_floor <= 0:
        raise ValueError(f"cannot fit below the floor: A={a_floor}, V={v_below}")
    depth = floor - bed
    b_raw = a_floor * depth / v_below - 1 if depth > 0 else -np.inf
    b = float(np.clip(b_raw, B_MIN, B_MAX))
    if b == b_raw:
        method = "bed at the published maximum depth"
    else:
        depth = v_below * (b + 1) / a_floor
        method = (
            f"published bed gave b={b_raw:.2f}; bound hit, b set to {b:g} and the bed moved "
            f"{abs(bed - (floor - depth)):.1f} m {'down' if floor - depth < bed else 'up'}"
        )
    c = a_floor / depth**b
    return PowerFit(h0=floor - depth, b=b, c=c, method=method)


def usable_shares(levels, volumes, fsl, swiss_floor, global_floor, dead, usable) -> dict:
    """Share of the usable volume above the swissALTI3D floor, between floors, below."""

    def uv(h):  # gross volume at h, but not below the dead volume
        return max(float(np.interp(h, levels, volumes)), dead)

    top, vs, vg = uv(fsl), uv(swiss_floor), uv(global_floor)
    return {
        "usable_share_swissalti3d_2m": round((top - vs) / usable, 3),
        "usable_share_global_dem_30m": round((vs - vg) / usable, 3),
        "usable_share_fitted": round((vg - dead) / usable, 3),
    }


# ---------------------------------------------------------------- full pipeline


def grid_path(slug: str) -> Path:
    return GRID_DIR / f"{slug}.npz"


def hybrid_path(slug: str) -> Path:
    return GRID_DIR / f"{slug}_hybrid.npz"


def build(slug: str, refresh: bool = False) -> dict:
    """Build the terrain grid, floor, join levels and the curve; write the curve CSV."""
    r = reservoir(slug)
    fsl = float(r["full_level_m"])
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    CURVE_DIR.mkdir(parents=True, exist_ok=True)
    path = grid_path(slug)
    if path.exists() and not refresh:
        g = load_grid(slug)
        floor, flat, flat_share = find_floor(g.z, g.outline)
        join = np.load(path)["join"]
    else:
        g = build_grid(slug)
        floor, flat, flat_share = find_floor(g.z, g.outline)
        cost = np.where(g.near_dam, g.zmax, g.z).astype("float64")
        # The flat patch is the lake surface at the floor: it joins at exactly the floor.
        cost = np.where(flat, floor, cost)
        join = join_levels(cost, flat, g.window)
        np.savez_compressed(
            path,
            z=g.z,
            zmax=g.zmax,
            year=g.year,
            outline=g.outline,
            window=g.window,
            near_dam=g.near_dam,
            transform=np.array(g.transform),
            join=join,
        )

    survey_years = g.year[flat]
    survey_year = int(np.bincount(survey_years[survey_years > 0]).argmax())
    coverage = float(np.isfinite(g.z[g.outline]).mean())

    # Global DEM below the swissALTI3D floor.
    from alpinehydro import globaldem

    dems = globaldem.fetch(slug, g.shape, g.transform)
    cands = [
        globaldem.assess(n, *dems[n], g.z, g.outline, flat, g.near_dam, g.window, floor)
        for n in globaldem.DEMS
    ]
    chosen = globaldem.choose(cands)
    if chosen is not None:
        gfloor = round(chosen.flat_level - chosen.offset, 2)
        bed = np.nan_to_num(dems[chosen.name][1] - chosen.offset, nan=floor)
        seed = flat & chosen.flat
        z_hyb = np.where(flat, np.clip(bed, gfloor, floor), g.z).astype("float64")
        z_hyb[seed] = gfloor
        cost = np.where(g.near_dam & ~flat, g.zmax, z_hyb)
        join = join_levels(cost, seed, g.window)
        lowest, low_src = gfloor, f"measured ({chosen.name}, 30 m, offset corrected)"
    else:
        z_hyb = np.where(flat, floor, g.z).astype("float64")
        lowest, low_src = floor, ""
    np.savez_compressed(hybrid_path(slug), z=z_hyb, join=join, lowest=lowest)

    # Measured part: lowest measured level to full level in 0.25 m steps.
    levels = np.round(np.arange(lowest, fsl, STEP), 2)
    levels = np.append(levels[levels < fsl - 1e-6], fsl)
    if floor not in levels and lowest < floor:
        levels = np.sort(np.append(levels, floor))
    area = level_area(join, levels)
    v_meas = np.concatenate([[0.0], np.cumsum(np.diff(levels) * (area[1:] + area[:-1]) / 2)])
    v_gross = float(r["gross_volume_mm3"])
    v_below = v_gross - v_meas[-1]
    v_swiss = v_meas[-1] - float(np.interp(floor, levels, v_meas))

    # Slope of A just above the lowest measured level (first 3 m).
    top = levels <= min(lowest + 3.0, fsl)
    slope = float(np.polyfit(levels[top][1:], area[top][1:], 1)[0]) if top.sum() > 3 else 0.0
    a_low = float(area[0])
    # sfoe1983 depth is measured from its own full level (before Mauvoisin was raised).
    published_bed = float(r.get("max_depth_reference_level_m", fsl)) - float(r["max_depth_m"])
    fit = fit_below_floor(a_low, v_below, lowest, published_bed)

    # Fitted part: h0 to the lowest measured level.
    below = np.round(np.arange(np.ceil(fit.h0 / STEP) * STEP, lowest, STEP), 2)
    src = np.where(levels < floor, low_src, "measured (swissALTI3D, 2 m)")
    curve = pd.concat(
        [
            pd.DataFrame(
                {
                    "level_m": below,
                    "area_km2": fit.area(below),
                    "volume_mm3": fit.volume(below),
                    "source": "fitted, not measured",
                }
            ),
            pd.DataFrame(
                {"level_m": levels, "area_km2": area, "volume_mm3": v_below + v_meas, "source": src}
            ),
        ],
        ignore_index=True,
    )
    dead = v_gross - float(r["usable_volume_mm3"])
    shares = usable_shares(
        curve["level_m"].to_numpy(),
        curve["volume_mm3"].to_numpy(),
        fsl,
        floor,
        lowest,
        dead,
        float(r["usable_volume_mm3"]),
    )
    edge = _touches_window_edge(join, g.window, fsl)
    info = {
        "slug": slug,
        "full_level_m": fsl,
        "floor_m": floor,
        "survey_year": survey_year,
        "flat_share_of_outline": round(flat_share, 3),
        "terrain_coverage_of_outline": round(coverage, 3),
        "global_dem": chosen.name if chosen else None,
        "global_dem_label": globaldem.INFO[chosen.name]["label"] if chosen else None,
        "global_dem_offset_m": round(chosen.offset, 2) if chosen else None,
        "global_dem_rmse_m": round(chosen.rmse, 2) if chosen else None,
        "global_dem_n": chosen.n if chosen else None,
        "global_floor_m": lowest if chosen else None,
        "global_dem_candidates": [c.row() for c in cands],
        **shares,
        "depth_share_above_floor": round((fsl - floor) / (fsl - fit.h0), 3),
        "area_at_lowest_measured_km2": round(a_low, 3),
        "area_at_floor_km2": round(float(np.interp(floor, levels, area)), 3),
        "area_at_full_km2": round(float(area[-1]), 3),
        "published_area_km2": r["area_km2"],
        "volume_above_floor_mm3": round(v_swiss, 2),
        "volume_between_floors_mm3": round(float(v_meas[-1]) - v_swiss, 2),
        "volume_below_lowest_measured_mm3": round(v_below, 2),
        "gross_volume_mm3": v_gross,
        "dead_volume_mm3": round(dead, 2),
        "h0_m": round(fit.h0, 2),
        "b": round(fit.b, 4),
        "c": round(fit.c, 6),
        "fit_method": fit.method,
        "b_bound_hit": "bound hit" in fit.method,
        "b_smooth_join_check": round(slope_join_b(a_low, v_below, slope), 2),
        "published_bed_m": published_bed,
        "full_extent_pixels_on_window_edge": edge,
    }
    write_curve(slug, curve, info, r)
    return info


def _touches_window_edge(join: np.ndarray, window: np.ndarray, level: float) -> int:
    """Count lake pixels at `level` that sit on the edge of the window (a leak warning)."""
    from scipy.ndimage import binary_erosion

    edge = window & ~binary_erosion(window)
    return int((edge & (join <= level)).sum())


def write_curve(slug: str, curve: pd.DataFrame, info: dict, r: dict) -> Path:
    path = CURVE_DIR / f"{slug}.csv"
    from alpinehydro import globaldem

    header = [
        f"# {r['name']}: level-area-volume curve on the 10 m UTM 32N grid",
        f"# credit: {CREDIT}",
        f"# full_level_m: {info['full_level_m']} ({r['full_level_source']})",
        f"# floor_m: {info['floor_m']} (flat water surface in swissALTI3D, "
        f"survey year {info['survey_year']}; measured at 2 m above it)",
    ]
    dem = info["global_dem"]
    if dem:
        meta = globaldem.INFO[dem]
        header += [
            f"# global_dem: {meta['label']}. credit: {meta['credit']}",
            f"# global_floor_m: {info['global_floor_m']} (flat water surface in {dem}, "
            "offset corrected)",
            f"# global_dem_offset_m: {info['global_dem_offset_m']} (mean {dem} minus "
            f"swissALTI3D on dry land from the floor to 30 m above it, n={info['global_dem_n']};"
            " subtracted)",
            f"# vertical_uncertainty_m: {info['global_dem_rmse_m']} (RMSE after the offset, "
            "same band) applies between global_floor_m and floor_m",
            "# resolution between the floors: 30 m DEM, bilinear onto the 10 m grid",
            f"# caveat: {meta['caveat']}",
        ]
    else:
        header += [
            "# global_dem: none eligible (no global DEM has a clearly flat water surface at "
            "least 10 m below floor_m); the curve below floor_m is fitted"
        ]
    header += [
        f"# h0_m: {info['h0_m']} (bed level; the published maximum depth gives "
        f"{info['published_bed_m']})",
        f"# b: {info['b']} (bounded to [1, 4]; a smooth join at the lowest measured level "
        f"would give {info['b_smooth_join_check']})",
        f"# c: {info['c']} (km2 per m^b)",
        f"# fit_method: {info['fit_method']}",
        f"# gross_volume_mm3: {info['gross_volume_mm3']} ({r['gross_volume_source']})",
        f"# usable_volume_mm3: {r['usable_volume_mm3']} ({r['usable_volume_source']})",
        f"# usable share measured at 2 m: {info['usable_share_swissalti3d_2m']}, "
        f"measured at 30 m: {info['usable_share_global_dem_30m']}, "
        f"fitted: {info['usable_share_fitted']}",
        "# Rows with source 'fitted, not measured' lie below the lowest measured level.",
        "# volume_mm3 is the gross volume from the bed (h0) up to level_m.",
    ]
    text = (
        "\n".join(header)
        + "\n"
        + curve.to_csv(index=False, float_format="%.5f", lineterminator="\n")
    )
    path.write_bytes(text.encode("utf-8"))
    (CURVE_DIR / f"{slug}.json").write_bytes((json.dumps(info, indent=2) + "\n").encode("utf-8"))
    return path


def load_grid(slug: str) -> Grid:
    d = np.load(grid_path(slug))
    return Grid(
        z=d["z"],
        zmax=d["zmax"],
        year=d["year"],
        outline=d["outline"],
        window=d["window"],
        transform=tuple(d["transform"]),
        near_dam=d["near_dam"],
    )


def load_join(slug: str) -> np.ndarray:
    """Join levels on the hybrid terrain (what the waterline method uses)."""
    return np.load(hybrid_path(slug))["join"]


def load_curve(slug: str) -> pd.DataFrame:
    return pd.read_csv(CURVE_DIR / f"{slug}.csv", comment="#")


def curve_info(slug: str) -> dict:
    return json.loads((CURVE_DIR / f"{slug}.json").read_text(encoding="utf-8"))
