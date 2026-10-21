"""Survey date of the swissALTI3D lake surface, from the swissSURFACE3D lidar points.

swissALTI3D holds each lake as a flat surface. Its STAC metadata give only a release year,
so the flight day is read from the GPS time of the lidar points (swissSURFACE3D, 1 km
tiles, deflate-zipped LAS). Each tile is streamed and parsed in memory; nothing is saved.

The lidar tile used for a swissALTI3D tile is the latest swissSURFACE3D year before the
swissALTI3D release year. As a check, the median height of the lidar water points
(class 9) in the tile is compared with the swissALTI3D floor: if they agree, the floor is
the water level on the flight day.
"""

from __future__ import annotations

import datetime as dt
import struct
import zlib
from collections import Counter

import numpy as np

STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.{c}/items"
GPS_EPOCH = dt.datetime(1980, 1, 6)
LEAP_SECONDS = 18  # GPS minus UTC since 2017
WATER = 9


def items(collection: str, key: str) -> dict[int, str]:
    """{year: asset url} for one 1 km tile key such as '2702-1219'."""
    import requests

    from alpinehydro import outlines

    e, n = (int(v) * 1000 for v in key.split("-"))
    lon0, lat0 = outlines.to_wgs84(e + 400, n + 400)
    lon1, lat1 = outlines.to_wgs84(e + 600, n + 600)
    url = STAC.format(c=collection) + f"?bbox={lon0},{lat0},{lon1},{lat1}&limit=50"
    out = {}
    for f in requests.get(url, timeout=60).json()["features"]:
        _, year, k = f["id"].split("_")
        if k == key:
            out[int(year)] = next(iter(f["assets"].values()))["href"]
    return out


def lidar_url(key: str, alti_year: int) -> tuple[int, str]:
    lidar = {y: u for y, u in items("swisssurface3d", key).items() if y < alti_year}
    if not lidar:
        raise RuntimeError(f"no swissSURFACE3D tile before {alti_year} for {key}")
    year = max(lidar)
    return year, lidar[year]


def gps_to_utc(t: np.ndarray, adjusted: bool) -> np.ndarray:
    """LAS GPS time (adjusted standard or GPS week seconds) to UTC dates (datetime64[D])."""
    if not adjusted:
        raise ValueError("GPS week time has no date; this tile cannot be dated")
    secs = t + 1e9 - LEAP_SECONDS
    return (np.datetime64(GPS_EPOCH, "s") + secs.astype("timedelta64[s]")).astype("M8[D]")


def scan(url: str) -> dict:
    """Point counts per UTC day and water-point heights for one lidar tile."""
    days: Counter = Counter()
    water_z: list[np.ndarray] = []
    if url.endswith(".copc.laz"):
        _scan_copc(url, days, water_z)
    else:
        _scan_zip(url, days, water_z)
    wz = np.concatenate(water_z) if water_z else np.array([])
    return {
        "days": {str(k): int(v) for k, v in sorted(days.items())},
        "water_points": int(wz.size),
        "water_median_m": round(float(np.median(wz)), 2) if wz.size else None,
        "water_iqr_m": round(float(np.subtract(*np.percentile(wz, [75, 25]))), 2)
        if wz.size
        else None,
    }


def _scan_copc(url: str, days: Counter, water_z: list, levels: int = 5) -> None:
    """Cloud-optimised LAZ: read only the coarse octree levels over HTTP (a sample)."""
    from laspy import CopcReader

    with CopcReader.open(url) as r:
        adjusted = bool(r.header.global_encoding.gps_time_type)
        p = r.query(level=range(0, levels))
    t = np.asarray(p.gps_time)
    for d, c in zip(*np.unique(gps_to_utc(t, adjusted), return_counts=True), strict=True):
        days[d] += int(c)
    cls = np.asarray(p.classification)
    water_z.append(np.asarray(p.z)[cls == WATER])


def _scan_zip(url: str, days: Counter, water_z: list, chunk: int = 1 << 20) -> None:
    """Deflate-zipped LAS: stream and parse every point in memory."""
    import requests

    inflate = zlib.decompressobj(-15)
    buf = b""
    head = None
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        raw = b""
        started = False
        for part in r.iter_content(chunk):
            if not started:
                raw += part
                if len(raw) < 30:
                    continue
                nl, el = struct.unpack("<HH", raw[26:30])
                part, started = raw[30 + nl + el :], True
            buf += inflate.decompress(part)
            if head is None:
                if len(buf) < 375:
                    continue
                head = _header(buf)
                buf = buf[head["offset"] :]
            n = len(buf) // head["size"]
            if n:
                _points(buf[: n * head["size"]], head, days, water_z)
                buf = buf[n * head["size"] :]


def _header(b: bytes) -> dict:
    fmt = b[104] & 0x3F
    if fmt not in (1, 3, 6, 7, 8):
        raise ValueError(f"point format {fmt} not handled")
    # Byte positions of classification and GPS time in the point record.
    cls, gps = (16, 22) if fmt >= 6 else (15, 20)
    return {
        "cls": cls,
        "gps": gps,
        "cls_mask": 0xFF if fmt >= 6 else 0x1F,
        "adjusted": bool(struct.unpack("<H", b[6:8])[0] & 1),
        "offset": struct.unpack("<I", b[96:100])[0],
        "size": struct.unpack("<H", b[105:107])[0],
        "zscale": struct.unpack("<d", b[147:155])[0],
        "zoff": struct.unpack("<d", b[171:179])[0],
    }


def _points(b: bytes, head: dict, days: Counter, water_z: list) -> None:
    a = np.frombuffer(b, np.uint8).reshape(-1, head["size"])
    t = a[:, head["gps"] : head["gps"] + 8].copy().view("<f8").ravel()
    for d, c in zip(*np.unique(gps_to_utc(t, head["adjusted"]), return_counts=True), strict=True):
        days[d] += int(c)
    water = (a[:, head["cls"]] & head["cls_mask"]) == WATER
    if water.any():
        z = a[water, 8:12].copy().view("<i4").ravel()
        water_z.append(z * head["zscale"] + head["zoff"])


def lake_tiles(slug: str) -> dict[str, float]:
    """{1 km LV95 tile key: km2 of the flat swissALTI3D lake surface in it}."""
    from pyproj import Transformer

    from alpinehydro import hypsometry

    g = hypsometry.load_grid(slug)
    floor = hypsometry.curve_info(slug)["floor_m"]
    flat = (np.abs(g.z - floor) <= hypsometry.FLAT_TOL_M) & g.outline
    r, c = np.where(flat)
    a, _, x0, _, e, y0 = g.transform
    to_lv95 = Transformer.from_crs(32632, 2056, always_xy=True).transform
    east, north = to_lv95(x0 + (c + 0.5) * a, y0 + (r + 0.5) * e)
    keys = [f"{int(i)}-{int(j)}" for i, j in zip(east // 1000, north // 1000, strict=True)]
    k, n = np.unique(keys, return_counts=True)
    return {
        str(key): round(float(v) * hypsometry.RES**2 / 1e6, 3) for key, v in zip(k, n, strict=True)
    }


def alti_years() -> dict[str, int]:
    """swissALTI3D release year per tile key, from the downloaded tile names."""
    from alpinehydro import hypsometry

    out = {}
    for p in hypsometry.TILE_DIR.glob("swissalti3d_*_2.tif"):
        _, year, key, _ = p.stem.split("_")
        out[key] = max(out.get(key, 0), int(year))
    return out


def dates(slug: str, min_km2: float = 0.0) -> list[dict]:
    """Lidar days and water heights for every tile of the flat lake surface (cached)."""
    import json

    from alpinehydro import config

    cache = config.INTERIM / "survey"
    cache.mkdir(parents=True, exist_ok=True)
    years = alti_years()
    rows = []
    for key, km2 in lake_tiles(slug).items():
        if km2 < min_km2 or key not in years:
            continue
        path = cache / f"{key}_{years[key]}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
        else:
            row = {"tile": key, "alti_year": years[key]}
            try:
                lidar_year, url = lidar_url(key, years[key])
                row.update({"lidar_year": lidar_year, **scan(url)})
            except RuntimeError as e:  # e.g. an all-water tile has no lidar tile
                row.update(
                    {"lidar_year": None, "days": {}, "water_median_m": None, "error": str(e)}
                )
            path.write_text(json.dumps(row), encoding="utf-8")
        rows.append({**row, "reservoir": slug, "flat_km2": km2})
    return rows


def edge_bias(slug: str, day: str, ref_level: float, max_days: int = 5) -> list[dict]:
    """Mask water area of Sentinel-2 scenes within max_days of a lidar day, against the
    curve area at the lidar water level (ref_level). Pulls the few scenes it needs."""
    import pandas as pd

    from alpinehydro import hypsometry, storage, water_mask

    s = water_mask.settings()
    d0 = pd.Timestamp(day, tz="UTC")
    scenes = water_mask.scene_list(slug, "s2", months=list(range(1, 13)))
    near = scenes[(scenes["time_utc"] - d0).abs() <= pd.Timedelta(days=max_days)].copy()
    if near.empty:
        return []
    near["clear_fraction"] = water_mask.clear_fractions(
        slug, "s2", near["date"].tolist(), months=list(range(1, 13))
    ).values
    g = hypsometry.load_grid(slug)
    hyb = np.load(hypsometry.hybrid_path(slug))
    lake_max = hyb["join"] <= float(hypsometry.reservoir(slug)["full_level_m"])
    curve = hypsometry.load_curve(slug)
    ref_area = float(np.interp(ref_level, curve["level_m"], curve["area_km2"]))
    out = []
    for r in near.itertuples():
        row = {"date": r.date, "clear_fraction": round(float(r.clear_fraction), 3)}
        if r.clear_fraction >= s["min_clear_fraction"]:
            path = water_mask.pull(
                slug, "s2", r.date, r.sun_azimuth, r.sun_zenith, months=list(range(1, 13))
            )
            m = water_mask.classify(water_mask.load_arrays(path), g.window, lake_max)
            area = storage.lake_water_area(m["water"] & lake_max)
            row.update(
                {
                    "flags": ";".join(m["flags"]) or "ok",
                    "water_km2": round(area, 3),
                    "ref_km2": round(ref_area, 3),
                    "shortfall_km2": round(ref_area - area, 3),
                    "shortfall_pct": round(100 * (ref_area - area) / ref_area, 2),
                }
            )
        out.append(row)
    return out
