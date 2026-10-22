"""H3 follow-up (POST-HOC), exactly as `prereg/H3_FOLLOWUP_PLAN.md` (tag v0.3-followup-plan).

Written after seeing H3a. Every number from here is labelled post-hoc and reported apart
from the pre-registered verdicts.

Primary: 1 July update, Total, walk-forward 2012 to 2026, full model
fill = a + b FSC(1 May, 1800 m) + c storage(1 July) + d PDD x G + e P, against C1 (storage
at 1 July), one-sided Clark-West. Secondary: 1 June and 1 August updates, and the
1 April model with FSC at or above 2500 m. Holm within these four tests only.

`ee` is imported inside functions only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config, earthengine, evaluate_snow, features_snow, snow

TAG = "alpinehydro-weekend5"
BAND_2500 = snow.SNOW_DIR / "band_polygons_2500.geojson"
T_CSV = snow.SNOW_DIR / "followup_era5land_t2m_2500.csv"
P_CSV = snow.SNOW_DIR / "followup_era5land_precip_1800.csv"
M_CSV = snow.SNOW_DIR / "followup_modis_2500_spring.csv"
G_JSON = snow.SNOW_DIR / "followup_glacier_share.json"
FEATURES = snow.SNOW_DIR / "features_followup.csv"
OUT = config.ROOT / "reports" / "checks" / "h3_followup_results.json"

YEARS = range(2001, 2027)
TEST_YEARS = list(range(2012, 2027))
UPDATES = {"jun1": (6, 1), "jul1": (7, 1), "aug1": (8, 1)}
PRIMARY = "jul1"
ERA5_LAG = 7
MODIS_LAG = 3
GLIMS_YEARS = ("2013", "2014", "2015", "2016")


# ---------------------------------------------------------------- Earth Engine pieces


def build_polygons_2500() -> Path:
    """The 2500 m band polygons, built once per canton on the MODIS grid (like 1800 m)."""
    import ee

    earthengine.init()
    ee.data.setWorkloadTag(TAG)
    masks = snow._band_masks((2500,))
    feats = []
    for region in snow.CANTONS:
        geom = ee.Geometry(snow.canton_geojson(region)["geometry"])
        m = masks.select("b2500")
        vec = m.updateMask(m).reduceToVectors(
            geometry=geom,
            maxPixels=1e10,
            geometryType="polygon",
            eightConnected=False,
            **snow.MODIS_GRID,
        )
        info = snow._get_info(vec.geometry(maxError=1), f"vectors {region} 2500")
        feats.append(
            {"type": "Feature", "geometry": info, "properties": {"region": region, "band_m": 2500}}
        )
        print(f"2500 m polygons: {region}")
    fc = {
        "type": "FeatureCollection",
        "credit": snow.CREDIT + "; Copernicus GLO-30 DEM",
        "note": "500 m MODIS pixels whose mean GLO-30 elevation is at or above 2500 m, "
        "inland water removed, inside each canton (H3 follow-up, post-hoc)",
        "features": feats,
    }
    BAND_2500.write_text(json.dumps(fc), encoding="utf-8")
    return BAND_2500


def glacier_share() -> dict:
    """Glacier area (GLIMS, SGI2016 epoch, union) per canton over its land at >= 2500 m."""
    import ee
    from pyproj import Geod
    from shapely.geometry import shape

    earthengine.init()
    ee.data.setWorkloadTag(TAG)
    geod = Geod(ellps="WGS84")
    sgi = ee.FeatureCollection("GLIMS/20230607").filter(
        ee.Filter.Or(*[ee.Filter.stringStartsWith("src_date", y) for y in GLIMS_YEARS])
    )
    band = json.loads(BAND_2500.read_text(encoding="utf-8"))
    out = {}
    for f in band["features"]:
        region = f["properties"]["region"]
        geom = ee.Geometry(snow.canton_geojson(region)["geometry"])
        img = ee.Image(0).byte().paint(sgi.filterBounds(geom), 1).selfMask()
        area = img.multiply(ee.Image.pixelArea()).reduceRegion(
            ee.Reducer.sum(), geom, scale=50, maxPixels=1e10
        )
        glacier_km2 = (snow._get_info(area, f"glacier {region}").get("constant") or 0) / 1e6
        band_km2 = abs(geod.geometry_area_perimeter(shape(f["geometry"]))[0]) / 1e6
        out[region] = {"glacier_km2": glacier_km2, "band2500_km2": band_km2}
        print(f"glacier {region}: {glacier_km2:.1f} km2 of {band_km2:.1f} km2 at 2500 m")
    g = sum(v["glacier_km2"] for v in out.values())
    b = sum(v["band2500_km2"] for v in out.values())
    out["Total"] = {"glacier_km2": g, "band2500_km2": b}
    for v in out.values():
        v["share"] = v["glacier_km2"] / v["band2500_km2"]
    G_JSON.write_text(
        json.dumps(
            {
                "source": "GLIMS/20230607 in Earth Engine, src_date 2013 to 2016 (SGI2016 "
                "epoch), unioned at 50 m; band area from band_polygons_2500.geojson",
                "credit": "GLIMS Consortium, GLIMS Glacier Database v1, NSIDC; Swiss Glacier "
                "Inventory (University of Zurich, GLAMOS)",
                "regions": out,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def era5_daily(variable: str, band: int, polygons: Path, start: str, end: str) -> pd.DataFrame:
    """Daily ERA5-Land mean over band pixels per canton (and Total): T in C, or P in mm."""
    import ee

    earthengine.init()
    ee.data.setWorkloadTag(TAG)
    src = "temperature_2m" if variable == "t2m" else "total_precipitation_sum"

    def conv(i):
        v = i.select(src)
        v = v.subtract(273.15) if variable == "t2m" else v.multiply(1000)
        return v.rename("v").copyProperties(i, ["system:time_start"])

    col = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(start, end).map(conv)
    stamps = snow._get_info(col.aggregate_array("system:time_start"), f"ERA5 {variable} {start}")
    days = [pd.Timestamp(ms, unit="ms").strftime("%Y-%m-%d") for ms in stamps]
    info = snow._get_info(
        snow._reduce_stack(col, "v", days, (band,), polygons), f"ERA5 {variable} {start}"
    )
    df = snow._from_sums(pd.DataFrame(snow._rows(info, days)))
    return snow._tidy(df, variable).drop(columns="valid_share")


def pull(years=YEARS, log=print) -> None:
    """T (2500 m) and P (1800 m) for 1 May to 1 August, MODIS 2500 m for 20 to 31 March."""
    cache = config.INTERIM / "followup"
    cache.mkdir(parents=True, exist_ok=True)
    for y in years:
        for name, fn in (
            ("t2m", lambda y: era5_daily("t2m", 2500, BAND_2500, f"{y}-05-01", f"{y}-08-01")),
            (
                "precip",
                lambda y: era5_daily(
                    "precip", 1800, snow.BAND_POLYGONS, f"{y}-05-01", f"{y}-08-01"
                ),
            ),
            (
                "modis2500",
                lambda y: snow.modis_daily(
                    f"{y}-03-20", f"{y}-04-01", bands=(2500,), polygons=BAND_2500, tag=TAG
                ),
            ),
        ):
            path = cache / f"{name}_{y}.csv"
            if path.exists():
                continue
            fn(y).to_csv(path, index=False)
            log(f"{name} {y} done")


def combine() -> None:
    cache = config.INTERIM / "followup"
    stamp = f"pulled with Earth Engine workload tag {TAG}; H3 follow-up (post-hoc)"
    for name, path, head in (
        ("t2m", T_CSV, "t2m: ERA5-Land daily mean 2 m temperature (C), mean over 2500 m band"),
        ("precip", P_CSV, "precip: ERA5-Land daily total precipitation (mm), mean over 1800 m"),
        ("modis2500", M_CSV, "fsc: MODIS FSC at or above 2500 m, H3 rules, 20 to 31 March"),
    ):
        df = pd.concat([pd.read_csv(p) for p in sorted(cache.glob(f"{name}_*.csv"))])
        if name == "modis2500":
            df = snow.finalise_modis(df)
            credit = snow.MODIS_CITATION
        else:
            credit = snow.ERA5_CREDIT
        snow.write_csv(df, path, [credit, head, stamp])


# ---------------------------------------------------------------- features


def _daily(path: Path, col: str, region: str) -> pd.Series:
    d = snow.read_csv(path)
    return d[d["region"] == region].set_index("date")[col].sort_index()


def build_features() -> pd.DataFrame:
    h3 = features_snow.load()
    h3 = h3[h3["band_m"] == 1800]
    st = features_snow.alpine_total(features_snow.load_inputs()[2])
    st["valid_time"] = pd.to_datetime(st["valid_time"])
    g = json.loads(G_JSON.read_text(encoding="utf-8"))["regions"]
    rows = []
    for region in snow.REGIONS:
        t, p = _daily(T_CSV, "t2m", region), _daily(P_CSV, "precip", region)
        m2500 = _daily(M_CSV, "fsc", region)
        sr = st[st["region"] == region]
        for y in YEARS:
            base = h3[(h3["region"] == region) & (h3["year"] == y)]
            may = base[base["issue"] == "may1"]
            apr = base[base["issue"] == "apr1"]
            if may.empty:
                continue
            common = {
                "year": y,
                "region": region,
                "y": float(may["end_fill_pp"].iloc[0]),
                "glacier_share": g[region]["share"],
            }
            for issue, (mo, da) in UPDATES.items():
                d = pd.Timestamp(y, mo, da)
                cut = d - pd.Timedelta(days=ERA5_LAG)
                days = pd.date_range(f"{y}-05-01", cut)
                tw, pw = t.reindex(days), p.reindex(days)
                full = tw.notna().all() and pw.notna().all()
                s = features_snow.starting_storage(sr, d)
                rows.append(
                    {
                        **common,
                        "issue": issue,
                        "issue_date": d.date(),
                        "era5_cutoff": cut.date(),
                        "era5_last": tw.dropna().index.max().date() if tw.notna().any() else None,
                        "snow": float(may["modis_fsc"].iloc[0]),
                        "pdd": float(tw.clip(lower=0).sum()) if full else np.nan,
                        "precip_mm": float(pw.sum()) if full else np.nan,
                        "start_fill_pp": float(s["fill"]) * 100 if s is not None else np.nan,
                        "start_valid_time": s["valid_time"].date() if s is not None else None,
                        "start_known_time": s["known_time"] if s is not None else None,
                    }
                )
            if not apr.empty:
                d = pd.Timestamp(y, 4, 1)
                cut = d - pd.Timedelta(days=MODIS_LAG)
                mean, n, last = features_snow.window_mean(m2500, cut)
                rows.append(
                    {
                        **common,
                        "issue": "apr1_2500",
                        "issue_date": d.date(),
                        "modis_cutoff": cut.date(),
                        "modis_last": last.date() if last is not None else None,
                        "modis_n_days": n,
                        "snow": mean,
                        "start_fill_pp": float(apr["start_fill_pp"].iloc[0]),
                        "start_valid_time": apr["start_valid_time"].iloc[0],
                        "start_known_time": apr["start_known_time"].iloc[0],
                    }
                )
    f = pd.DataFrame(rows)
    f["pddg"] = f["pdd"] * f["glacier_share"]
    return f


def write_features(f: pd.DataFrame) -> Path:
    return snow.write_csv(
        f,
        FEATURES,
        [
            "H3 follow-up features (POST-HOC, prereg/H3_FOLLOWUP_PLAN.md).",
            "pdd: sum of max(0, T) from 1 May to issue minus 7 days, ERA5-Land, 2500 m band;",
            "pddg = pdd x glacier_share; precip_mm: same days, 1800 m band; snow: MODIS FSC",
            "1 May 1800 m (updates) or 2500 m 8-day mean to 29 March (apr1_2500).",
            snow.ERA5_CREDIT,
            snow.MODIS_CITATION,
        ],
    )


# ---------------------------------------------------------------- scoring


def _cols(issue: str) -> list[str]:
    return ["snow", "start_fill_pp"] + ([] if issue == "apr1_2500" else ["pddg", "precip_mm"])


def walk_forward(d: pd.DataFrame, issue: str) -> pd.DataFrame:
    cols = _cols(issue)
    ok = d.dropna(subset=[*cols, "y"])
    rows = []
    for y in TEST_YEARS:
        test, train = ok[ok["year"] == y], ok[ok["year"] < y]
        if test.empty or len(train) < 10:
            continue
        rows.append(
            {
                "year": y,
                "y": float(test["y"].iloc[0]),
                "full": float(evaluate_snow.predict(train, test, cols, "y")[0]),
                "c1": float(evaluate_snow.predict(train, test, ["start_fill_pp"], "y")[0]),
                "n_train": len(train),
            }
        )
    return pd.DataFrame(rows)


def _score(o: pd.DataFrame) -> dict:
    y, full, c1 = (o[c].to_numpy(float) for c in ("y", "full", "c1"))
    return {
        "n": len(o),
        "years": [int(o["year"].min()), int(o["year"].max())],
        "rmse_full": float(np.sqrt(np.mean((y - full) ** 2))),
        "rmse_c1": float(np.sqrt(np.mean((y - c1) ** 2))),
        "skill_vs_c1": evaluate_snow.skill(y, full, c1),
        "clark_west_vs_c1": evaluate_snow.clark_west(y, full, c1),
    }


def run(f: pd.DataFrame | None = None, write: bool = True) -> dict:
    f = build_features() if f is None else f
    res: dict = {"label": "POST-HOC (H3_FOLLOWUP_PLAN.md, v0.3-followup-plan)", "tests": {}}
    for issue in ["jul1", "jun1", "aug1", "apr1_2500"]:
        d = f[(f["region"] == "Total") & (f["issue"] == issue)].sort_values("year")
        wf = walk_forward(d, issue)
        cols = _cols(issue)
        ok = d.dropna(subset=[*cols, "y"])
        res["tests"][issue] = {
            **_score(wf),
            "dropped_years": sorted(set(d["year"]) - set(ok["year"])),
            "case_2026": wf[wf["year"] == 2026].round(2).to_dict(orient="records"),
            "wf_rows": wf.round(3).to_dict(orient="records"),
        }
    p = {k: v["clark_west_vs_c1"]["p_one_sided"] for k, v in res["tests"].items()}
    res["holm"] = evaluate_snow.holm(p)
    prim = res["tests"][PRIMARY]
    res["primary_passes"] = bool(prim["skill_vs_c1"] > 0 and res["holm"][PRIMARY] < 0.05)
    res["verdict"] = (
        "added skill after 1 May (post-hoc)"
        if res["primary_passes"]
        else "no added skill after 1 May (post-hoc)"
    )
    regions = {}
    for region in snow.CANTONS:
        d = f[(f["region"] == region) & (f["issue"] == PRIMARY)].sort_values("year")
        regions[region] = _score(walk_forward(d, PRIMARY))
    res["primary_by_region_uncorrected"] = regions
    if write:
        OUT.write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    return res
