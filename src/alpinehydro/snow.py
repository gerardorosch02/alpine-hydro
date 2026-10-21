"""Part C: regional snow series from MODIS and ERA5-Land (H3 analysis plan, sections 2-5).

Regions are the canton outlines of Valais, Graubünden and Ticino from swisstopo
swissBOUNDARIES3D, plus their union ("Total"). The elevation band is every 500 m
MODIS pixel whose mean Copernicus GLO-30 elevation is at or above 1800 m (2000 m as
robustness), excluding MODIS inland water.

Earth Engine work is region statistics only (reduceRegions), never an image export.
`ee` is imported inside functions only (CI has no login).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import shapefile
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from alpinehydro import config, earthengine
from alpinehydro.outlines import _HttpRange, to_wgs84

SB_RELEASE = "swissboundaries3d_2026-01"
SB_URL = (
    f"https://data.geo.admin.ch/ch.swisstopo.swissboundaries3d/{SB_RELEASE}/"
    f"{SB_RELEASE}_2056_5728.shp.zip"
)
SB_LAYER = "swissBOUNDARIES3D_1_5_TLM_KANTONSGEBIET"
SB_DIR = config.RAW / SB_RELEASE
OUTLINE_DIR = config.DATA / "external" / "outlines"
CREDIT = "Source: Federal Office of Topography swisstopo (swissBOUNDARIES3D)"
SIMPLIFY_M = 50.0

# SFOE region -> swissBOUNDARIES3D canton NAME.
CANTONS = {"Wallis": "Valais", "Graubuenden": "Graubünden", "Tessin": "Ticino"}
REGIONS = [*CANTONS, "Total"]
BANDS_M = (1800, 2000)

MODIS_START = "2000-02-24"
ERA5_START = "1990-01-01"
GAP_FILL_DAYS = 8
MIN_VALID_SHARE = 0.70
SNOW_DIR = config.PROCESSED / "snow"
EE_TAG = "alpinehydro-weekend4"
# The MODIS sinusoidal 500 m grid (MOD10A1 NDSI_Snow_Cover), passed explicitly to every
# reduction: a projection object without a transform made Earth Engine fail.
MODIS_GRID = {
    "crs": "SR-ORG:6974",
    "crsTransform": [463.3127165279165, 0, -20015109.354, 0, -463.3127165279167, 10007554.677003],
}

MODIS_CITATION = (
    "Hall, D. K. and G. A. Riggs (2021). MODIS/Terra and MODIS/Aqua Snow Cover Daily L3 "
    "Global 500m SIN Grid, Version 61 (MOD10A1, MYD10A1). NASA National Snow and Ice "
    "Data Center DAAC. Accessed through Google Earth Engine."
)
ERA5_CREDIT = (
    "Contains modified Copernicus Climate Change Service information (ERA5-Land, "
    "Muñoz Sabater 2019, C3S Climate Data Store). Accessed through Google Earth Engine."
)


# ---------------------------------------------------------------- outlines


def _canton_shapes() -> dict[str, Any]:
    """Canton polygons in LV95 from the swissBOUNDARIES3D canton layer."""
    SB_DIR.mkdir(parents=True, exist_ok=True)
    stem = SB_DIR / SB_LAYER
    if not stem.with_suffix(".shp").exists():
        with zipfile.ZipFile(_HttpRange(SB_URL)) as z:
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                (SB_DIR / f"{SB_LAYER}{ext}").write_bytes(z.read(f"{SB_LAYER}{ext}"))
    reader = shapefile.Reader(str(stem), encoding="utf-8")
    parts: dict[str, list] = {name: [] for name in CANTONS.values()}
    for rec in reader.iterShapeRecords():
        name = rec.record.as_dict().get("NAME")
        if name in parts:
            geom = shape(rec.shape.__geo_interface__)
            # Drop the Z coordinate of the 3D boundaries.
            parts[name].append(transform(lambda x, y, z=None: (x, y), geom))
    return {region: unary_union(parts[name]) for region, name in CANTONS.items()}


def _round6(text: str) -> float:
    return round(float(text), 6)


def build_outlines() -> dict[str, dict]:
    """Write one small GeoJSON per canton (EPSG:4326, simplified by 50 m)."""
    OUTLINE_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for region, geom in _canton_shapes().items():
        simple = geom.simplify(SIMPLIFY_M, preserve_topology=True)
        wgs = transform(to_wgs84, simple)
        fc = {
            "type": "FeatureCollection",
            "crs_note": "EPSG:4326 (WGS84 lon/lat), computed from LV95 (EPSG:2056)",
            "credit": CREDIT,
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "region": region,
                        "canton": CANTONS[region],
                        "release": SB_RELEASE,
                        "area_km2_lv95": round(geom.area / 1e6, 1),
                        "simplified_m": SIMPLIFY_M,
                    },
                    "geometry": json.loads(
                        json.dumps(mapping(wgs)), parse_float=lambda s: round(float(s), 6)
                    ),
                }
            ],
        }
        path = OUTLINE_DIR / f"canton_{region.lower()}.geojson"
        path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        out[region] = {
            "path": path.relative_to(config.ROOT).as_posix(),
            "area_km2": round(geom.area / 1e6, 1),
        }
    return out


def canton_geojson(region: str) -> dict:
    path = OUTLINE_DIR / f"canton_{region.lower()}.geojson"
    return json.loads(path.read_text(encoding="utf-8"))["features"][0]


# ---------------------------------------------------------------- Earth Engine pieces


def _regions_fc():
    """The three cantons. Total is built from their sums (an EE union failed: object too large)."""
    import ee

    return ee.FeatureCollection(
        [ee.Feature(ee.Geometry(canton_geojson(r)["geometry"]), {"region": r}) for r in CANTONS]
    )


def _reduce_each(img, reducer, fc, **grid):
    """One reduceRegion per canton. reduceRegions over all three failed (object too large)."""
    import ee

    return fc.map(
        lambda f: ee.Feature(
            None, img.reduceRegion(reducer, f.geometry(), maxPixels=1e10, **grid)
        ).set("region", f.get("region"))
    )


def _modis_proj():
    import ee

    return ee.ImageCollection("MODIS/061/MOD10A1").first().select("NDSI_Snow_Cover").projection()


def _band_masks():
    """One 0/1 band per elevation threshold on the MODIS grid, inland water removed."""
    import ee

    proj = _modis_proj()
    dem_col = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM")
    dem = dem_col.mosaic().setDefaultProjection(dem_col.first().projection())
    dem500 = dem.reduceResolution(ee.Reducer.mean(), maxPixels=1024).reproject(proj)
    # MODIS uses a static land/water mask; class 237 is inland water.
    water = (
        ee.ImageCollection("MODIS/061/MOD10A1")
        .filterDate("2020-07-01", "2020-07-08")
        .map(lambda i: i.select("NDSI_Snow_Cover_Class").eq(237).unmask(0))
        .max()
        .reproject(proj)
    )
    return ee.Image.cat([dem500.gte(t).And(water.Not()).rename(f"b{t}") for t in BANDS_M])


def mask_areas() -> pd.DataFrame:
    """Band area per region from the 30 m DEM and from 500 m MODIS pixels."""
    import ee

    earthengine.init()
    fc = _regions_fc()
    dem_col = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").select("DEM")
    dem = dem_col.mosaic().setDefaultProjection(dem_col.first().projection())
    area30 = ee.Image.cat(
        [ee.Image.pixelArea().updateMask(dem.gte(t)).rename(f"a{t}") for t in BANDS_M]
        + [ee.Image.pixelArea().rename("all")]
    )
    r30 = _reduce_each(area30, ee.Reducer.sum(), fc, scale=30, crs="EPSG:4326").getInfo()
    masks = _band_masks()
    a500 = masks.multiply(ee.Image.pixelArea()).addBands(ee.Image.pixelArea().rename("all"))
    r500 = _reduce_each(a500, ee.Reducer.sum(), fc, **MODIS_GRID).getInfo()
    rows = []
    for f30, f500 in zip(r30["features"], r500["features"], strict=True):
        p30, p500 = f30["properties"], f500["properties"]
        for t in BANDS_M:
            rows.append(
                {
                    "region": p30["region"],
                    "band_m": t,
                    "area_km2_dem30": p30[f"a{t}"] / 1e6,
                    "area_km2_modis500": p500[f"b{t}"] / 1e6,
                    "region_km2": p30["all"] / 1e6,
                }
            )
    df = pd.DataFrame(rows)
    total = df.groupby("band_m", as_index=False)[
        ["area_km2_dem30", "area_km2_modis500", "region_km2"]
    ].sum()
    df = pd.concat([df, total.assign(region="Total")], ignore_index=True)
    df["share_of_region"] = df["area_km2_dem30"] / df["region_km2"]
    return df


def _fsc(img):
    """FSC from NDSI_Snow_Cover (0-100; flags are masked), Salomonson and Appel."""
    n = img.select("NDSI_Snow_Cover")
    return (
        n.divide(100).multiply(1.45).subtract(0.01).clamp(0, 1).rename("fsc").updateMask(n.lte(100))
    )


def _modis_daily_collection(start: str, end: str):
    """Combined Terra/Aqua FSC per day, gap-filled from the previous 8 days.

    The Earth Engine MOD10A1/MYD10A1 v6.1 carry no view zenith band, so the zenith
    is always unknown: Terra where Terra is valid, else Aqua.
    """
    import ee

    s, e = ee.Date(start), ee.Date(end)
    pad = s.advance(-GAP_FILL_DAYS, "day")
    terra = ee.ImageCollection("MODIS/061/MOD10A1").filterDate(pad, e)
    aqua = ee.ImageCollection("MODIS/061/MYD10A1").filterDate(pad, e)
    empty = ee.Image.constant(0).rename("fsc").updateMask(ee.Image.constant(0)).toFloat()

    def combined(day_offset):
        d = pad.advance(day_offset, "day")
        nxt = d.advance(1, "day")
        aq = ee.ImageCollection([empty]).merge(aqua.filterDate(d, nxt).map(_fsc)).mosaic()
        te = ee.ImageCollection([empty]).merge(terra.filterDate(d, nxt).map(_fsc)).mosaic()
        # mosaic() puts the last image on top: Terra where valid, else Aqua.
        fsc = ee.ImageCollection([aq.select("fsc"), te.select("fsc")]).mosaic()
        t = ee.Image.constant(d.millis().divide(86400000)).toFloat().rename("t")
        return fsc.addBands(t.updateMask(fsc.mask())).set("system:time_start", d.millis())

    n_days = e.difference(pad, "day").round()
    daily = ee.ImageCollection(ee.List.sequence(0, n_days.subtract(1)).map(combined))

    def filled(day_offset):
        d = s.advance(day_offset, "day")
        window = daily.filterDate(d.advance(-GAP_FILL_DAYS, "day"), d.advance(1, "day"))
        return window.qualityMosaic("t").select("fsc").set("system:time_start", d.millis())

    n_out = e.difference(s, "day").round()
    return ee.ImageCollection(ee.List.sequence(0, n_out.subtract(1)).map(filled))


def _reduce_daily(daily, value_band: str):
    """Per day and canton: sums of the value, of valid band pixels and of band pixels.

    Sums (weighted by pixel coverage) let the Total be built exactly as the mean over
    all valid pixels of the three cantons.
    """
    import ee

    masks = _band_masks()
    fc = _regions_fc()

    def per_day(img):
        bands = []
        v = img.select(value_band)
        for t in BANDS_M:
            m = masks.select(f"b{t}")
            ok = m.And(v.mask().gt(0))
            bands += [
                v.updateMask(ok).rename(f"s{t}"),
                ok.updateMask(ok).rename(f"nv{t}"),
                m.updateMask(m).rename(f"nb{t}"),
            ]
        stats = _reduce_each(ee.Image.cat(bands), ee.Reducer.sum(), fc, **MODIS_GRID)
        date = ee.Date(img.get("system:time_start")).format("YYYY-MM-dd")
        return stats.map(lambda f: f.set("date", date))

    return daily.map(per_day).flatten()


def _rows(fc_info: dict) -> list[dict]:
    rows = []
    for f in fc_info["features"]:
        p = f["properties"]
        for t in BANDS_M:
            rows.append(
                {
                    "date": p["date"],
                    "region": p["region"],
                    "band_m": t,
                    "s": p.get(f"s{t}") or 0.0,
                    "nv": p.get(f"nv{t}") or 0.0,
                    "nb": p.get(f"nb{t}") or 0.0,
                }
            )
    return rows


def _from_sums(raw: pd.DataFrame) -> pd.DataFrame:
    """Region values and valid shares from the sums, plus the Total of the three cantons."""
    total = raw.groupby(["date", "band_m"], as_index=False)[["s", "nv", "nb"]].sum()
    df = pd.concat([raw, total.assign(region="Total")], ignore_index=True)
    df["value"] = (df["s"] / df["nv"]).where(df["nv"] > 0)
    df["valid_share"] = df["nv"] / df["nb"]
    return df[["date", "region", "band_m", "value", "valid_share"]]


def _get_info(obj, label: str, tries: int = 3):
    for k in range(tries):
        try:
            return obj.getInfo()
        except Exception as exc:  # noqa: BLE001 - retry transient Earth Engine errors
            if k == tries - 1:
                raise
            print(f"{label}: retry after {type(exc).__name__}")
            time.sleep(10)


def _chunks(start: str, end: str, months: int) -> list[tuple[str, str]]:
    out, s = [], pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while s < end_ts:
        e = min(s + pd.DateOffset(months=months), end_ts)
        out.append((s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")))
        s = e
    return out


def modis_daily(start: str, end: str, months_per_call: int = 3) -> pd.DataFrame:
    """Daily regional FSC and valid share, [start, end), pulled in small tables."""
    import ee

    earthengine.init()
    ee.data.setWorkloadTag(EE_TAG)
    rows = []
    for s, e in _chunks(start, end, months_per_call):
        info = _get_info(_reduce_daily(_modis_daily_collection(s, e), "fsc"), f"MODIS {s}")
        rows += _rows(info)
        print(f"MODIS {s} to {e}: {len(info['features'])} region-days")
    return _tidy(_from_sums(pd.DataFrame(rows)), "fsc")


def era5_swe_daily(start: str, end: str, months_per_call: int = 12) -> pd.DataFrame:
    """Daily mean ERA5-Land SWE (mm) over the same band pixels, [start, end)."""
    import ee

    earthengine.init()
    ee.data.setWorkloadTag(EE_TAG)
    rows = []
    for s, e in _chunks(start, end, months_per_call):
        col = (
            ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
            .filterDate(s, e)
            .select("snow_depth_water_equivalent")
            .map(lambda i: i.multiply(1000).rename("swe").copyProperties(i, ["system:time_start"]))
        )
        info = _get_info(_reduce_daily(col, "swe"), f"ERA5 {s}")
        rows += _rows(info)
        print(f"ERA5 {s} to {e}: {len(info['features'])} region-days")
    df = _tidy(_from_sums(pd.DataFrame(rows)), "swe_mm")
    return df.drop(columns="valid_share")


def _tidy(df: pd.DataFrame, name: str) -> pd.DataFrame:
    df = df.rename(columns={"value": name})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.sort_values(["band_m", "region", "date"]).reset_index(drop=True)


def finalise_modis(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the 70% valid-share rule: FSC is set missing on days below it."""
    out = df.copy()
    out["missing"] = out["valid_share"].isna() | (out["valid_share"] < MIN_VALID_SHARE)
    out.loc[out["missing"], "fsc"] = float("nan")
    return out


def write_csv(df: pd.DataFrame, path: Path, header: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    for line in header:
        buf.write(f"# {line}\n")
    df.to_csv(buf, index=False, float_format="%.5f", lineterminator="\n")
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, comment="#")
    df["date"] = pd.to_datetime(df["date"])
    return df


def today_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
