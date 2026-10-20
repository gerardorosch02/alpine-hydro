"""Reservoir outlines from swissTLM3D and the 300 m analysis window.

swissTLM3D stores lake shorelines as 3D lines in the layer TLM_STEHENDES_GEWAESSER.
The lines of one lake are joined into a polygon. Their height is the water level on
the mapping date, which is usually a few metres below full supply, so the outline is
"as mapped", not a full-supply outline. The full-supply extent comes from the terrain
model in hypsometry.py, and the analysis window covers both.

Only the shoreline layer (about 67 MB) is pulled out of the 3.6 GB national zip, with
HTTP range requests.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer
from shapely import set_precision
from shapely.geometry import LineString, mapping, shape
from shapely.ops import polygonize, transform, unary_union

from alpinehydro import config

TLM_RELEASE = "swisstlm3d_2026-02"
TLM_URL = f"https://data.geo.admin.ch/ch.swisstopo.swisstlm3d/{TLM_RELEASE}/{TLM_RELEASE}_2056_5728.shp.zip"
TLM_LAYER = "TLM_GEWAESSER/swissTLM3D_TLM_STEHENDES_GEWAESSER"
TLM_DIR = config.INTERIM / TLM_RELEASE
OUTLINE_DIR = config.DATA / "external" / "outlines"
CREDIT = "Source: Federal Office of Topography swisstopo"
BUFFER_M = 300.0
# swissTLM3D lake names (NAME attribute) for each reservoir slug.
TLM_NAMES = {
    "sihlsee": "Sihlsee",
    "gruyere": "Lac de la Gruyère",
    "dix": "Lac des Dix",
    "emosson": "Lac d'Emosson",
    "mauvoisin": "Lac de Mauvoisin",
    "lei": "Lago di Lei",
    "grimsel": "Grimselsee",
}

to_wgs84 = Transformer.from_crs(2056, 4326, always_xy=True).transform
to_lv95 = Transformer.from_crs(4326, 2056, always_xy=True).transform


class _HttpRange(io.RawIOBase):
    """Read-only, seekable view of a remote file through HTTP range requests."""

    def __init__(self, url: str):
        self.url, self.pos = url, 0
        self.size = int(requests.head(url, timeout=60).headers["Content-Length"])

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        r = requests.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=120)
        r.raise_for_status()
        n = len(r.content)
        b[:n] = r.content
        self.pos += n
        return n


def download_tlm_shorelines() -> Path:
    """Extract the standing-water layer into data/interim/ (cached)."""
    shp = TLM_DIR / f"{TLM_LAYER}.shp"
    if shp.exists():
        return shp
    z = zipfile.ZipFile(io.BufferedReader(_HttpRange(TLM_URL), buffer_size=1 << 20))
    for info in z.infolist():
        if info.filename.startswith(TLM_LAYER) and not info.filename.endswith(".lock"):
            z.extract(info, TLM_DIR)
    return shp


def lake_polygon(slug: str, shp: Path | None = None) -> tuple[Any, dict]:
    """Join one lake's shoreline lines into a polygon in LV95. Returns (polygon, info)."""
    import shapefile  # pyshp

    shp = shp or download_tlm_shorelines()
    reader = shapefile.Reader(str(shp), encoding="utf-8", encodingErrors="replace")
    name = TLM_NAMES[slug]
    lines, zs, years = [], [], []
    for sr in reader.iterShapeRecords():
        if sr.record["NAME"] != name:
            continue
        lines.append(LineString(sr.shape.points))
        zs.extend(sr.shape.z)
        years.append(sr.record["REVISION_J"])
    if not lines:
        raise ValueError(f"no swissTLM3D shoreline named {name!r}")
    polys = sorted(polygonize(unary_union(lines)), key=lambda p: -p.area)
    lake = polys[0]
    zs_sorted = sorted(zs)
    info = {
        "tlm_name": name,
        "tlm_release": TLM_RELEASE,
        "tlm_segments": len(lines),
        # Median shoreline height: the water level on the mapping date.
        "tlm_level_m": round(zs_sorted[len(zs_sorted) // 2], 2),
        "tlm_revision_years": sorted(set(years)),
        "area_km2": round(lake.area / 1e6, 4),
    }
    return lake, info


def window(lake_lv95, buffer_m: float = BUFFER_M):
    """Analysis window: the outline buffered by 300 m (in LV95 metres)."""
    return lake_lv95.buffer(buffer_m)


def write_geojson(path: Path, geom_lv95, properties: dict) -> None:
    feature = {
        "type": "Feature",
        "properties": properties,
        # 1e-6 degrees is about 0.1 m, far finer than the 10 m analysis grid.
        "geometry": mapping(set_precision(transform(to_wgs84, geom_lv95), 1e-6)),
    }
    fc = {
        "type": "FeatureCollection",
        "crs_note": "EPSG:4326 (WGS84 lon/lat), computed from LV95 (EPSG:2056)",
        "features": [feature],
    }
    path.write_text(json.dumps(fc, indent=1) + "\n", encoding="utf-8", newline="\n")


def load(slug: str, kind: str = "outline"):
    """Load an outline or window from data/external/outlines/ as a shapely geometry in LV95."""
    fc = json.loads((OUTLINE_DIR / f"{slug}_{kind}.geojson").read_text(encoding="utf-8"))
    return transform(to_lv95, shape(fc["features"][0]["geometry"]))


def build(slug: str) -> dict:
    """Write <slug>_outline.geojson and <slug>_window.geojson. Returns the outline info."""
    OUTLINE_DIR.mkdir(parents=True, exist_ok=True)
    lake, info = lake_polygon(slug)
    note = (
        f"swissTLM3D {TLM_RELEASE}, layer TLM_STEHENDES_GEWAESSER, shoreline lines named "
        f"{info['tlm_name']!r} joined into a polygon. Shoreline height is the water level on "
        "the mapping date, not full supply. " + CREDIT
    )
    write_geojson(
        OUTLINE_DIR / f"{slug}_outline.geojson", lake, {"slug": slug, **info, "source": note}
    )
    write_geojson(
        OUTLINE_DIR / f"{slug}_window.geojson",
        window(lake),
        {"slug": slug, "buffer_m": BUFFER_M, "source": "300 m buffer of the outline. " + CREDIT},
    )
    return info


def jrc_check(slug: str) -> dict:
    """Compare the outline with JRC Global Surface Water max_extent inside the window.

    One reduceRegion call per reservoir at 30 m. Returns areas and intersection over union.
    """
    import ee

    from alpinehydro.earthengine import init

    init()
    lake = load(slug, "outline")
    win = load(slug, "window")
    ee_lake = ee.Geometry(mapping(transform(to_wgs84, lake)))
    ee_win = ee.Geometry(mapping(transform(to_wgs84, win)))
    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("max_extent").eq(1)
    inside = ee.Image.constant(0).paint(ee.FeatureCollection([ee.Feature(ee_lake)]), 1)
    area = ee.Image.pixelArea()
    stack = ee.Image.cat(
        area.updateMask(jrc).rename("jrc"),
        area.updateMask(inside).rename("tlm"),
        area.updateMask(jrc.And(inside)).rename("both"),
    )
    s = stack.reduceRegion(ee.Reducer.sum(), ee_win, scale=30, maxPixels=1e8).getInfo()
    jrc_a, tlm_a, both = (s[k] / 1e6 for k in ("jrc", "tlm", "both"))
    return {
        "slug": slug,
        "tlm_area_km2": round(tlm_a, 3),
        "jrc_max_extent_km2": round(jrc_a, 3),
        "iou": round(both / (jrc_a + tlm_a - both), 3),
    }
