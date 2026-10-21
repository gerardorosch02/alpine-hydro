"""MODIS fallback (weekend 5): the same daily regional snow cover from another sensor.

Candidates are built exactly like the MODIS series (H3 plan section 4, applied to their
own grid): FSC per pixel, each invalid pixel takes its most recent valid value from the
previous 8 days, the regional value is the mean over valid pixels inside the 1800 m band
of each canton, and a day is missing if fewer than 70% of the band pixels are valid.
The band is the committed MODIS band polygons (band_polygons.geojson), rasterised by pixel
centre on the candidate's grid, so the area is the same land as for MODIS.

Selection rule (fixed before any candidate was compared with MODIS):
- eligible: correlation of daily regional values with MODIS >= 0.9 and typical
  publication lag <= 5 days;
- among eligible candidates, the lower mean absolute difference against MODIS wins;
- if none is eligible, the tracker uses MODIS alone and says so.

Use in the tracker: a day takes the fallback value only if MODIS has no valid value on
that day and the 6 days before it (7 days in a row). The fallback value is corrected
with a linear fit on the overlap (MODIS = a + b x candidate, per region) and labelled
"fallback". The fallback never enters any H3 test.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config
from alpinehydro.snow import BAND_POLYGONS, GAP_FILL_DAYS, MIN_VALID_SHARE

REGIONS3 = ["Wallis", "Graubuenden", "Tessin"]
MIN_CORR = 0.9
MAX_LAG_DAYS = 5
SWITCH_DAYS = 7
OVERLAP_SEASONS = [("2024-10-01", "2025-06-30"), ("2025-10-01", "2026-06-30")]
OUT_DIR = config.PROCESSED / "snow"


# ---------------------------------------------------------------- grid and masks


def band_masks(transform, shape: tuple[int, int], crs: str, band: int = 1800) -> dict:
    """Boolean mask per canton: pixel centres inside the MODIS band polygons."""
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import shape as to_shape
    from shapely.ops import transform as reproject

    fc = json.loads(Path(BAND_POLYGONS).read_text(encoding="utf-8"))
    to = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    out = {}
    for f in fc["features"]:
        p = f["properties"]
        if p["band_m"] != band:
            continue
        geom = reproject(to, to_shape(f["geometry"]))
        out[p["region"]] = rasterize(
            [(geom, 1)], out_shape=shape, transform=transform, fill=0, dtype="uint8"
        ).astype(bool)
    return out


def fsc_from_ndsi(ndsi: np.ndarray) -> np.ndarray:
    """Salomonson and Appel FSC from NDSI snow cover 0-100; any other value is invalid."""
    n = ndsi.astype("float32")
    valid = (n >= 0) & (n <= 100)
    f = np.clip(-0.01 + 1.45 * n / 100.0, 0.0, 1.0)
    return np.where(valid, f, np.nan).astype("float32")


# ---------------------------------------------------------------- daily series


def regional_sums(fsc: np.ndarray, masks: dict) -> dict:
    """Per canton: sum of FSC over valid band pixels, valid count and band count."""
    ok = np.isfinite(fsc)
    return {
        r: (float(np.nansum(np.where(m & ok, fsc, 0.0))), int((m & ok).sum()), int(m.sum()))
        for r, m in masks.items()
    }


def daily_series(days: list[pd.Timestamp], load, masks: dict) -> pd.DataFrame:
    """Daily regional FSC with the 8-day per-pixel gap fill and the 70% rule.

    `load(day)` returns the FSC array of that day (NaN = invalid), or None if no data.
    Pixels keep their most recent valid value for GAP_FILL_DAYS days; older values expire.
    """
    shape = next(iter(masks.values())).shape
    last = np.full(shape, np.nan, dtype="float32")
    age = np.full(shape, 10_000, dtype="int32")
    rows = []
    for d in days:
        arr = load(d)
        age += 1
        if arr is not None:
            fresh = np.isfinite(arr)
            last[fresh] = arr[fresh]
            age[fresh] = 0
        filled = np.where(age <= GAP_FILL_DAYS, last, np.nan)
        for r, (s, nv, nb) in regional_sums(filled, masks).items():
            rows.append(
                {
                    "date": d.date(),
                    "region": r,
                    "s": s,
                    "nv": nv,
                    "nb": nb,
                    "has_data": arr is not None,
                }
            )
    return finalise(pd.DataFrame(rows))


def finalise(raw: pd.DataFrame) -> pd.DataFrame:
    """Region values, the Total of the three cantons, and the 70% valid-share rule."""
    total = raw.groupby("date", as_index=False).agg(
        s=("s", "sum"), nv=("nv", "sum"), nb=("nb", "sum"), has_data=("has_data", "max")
    )
    df = pd.concat([raw, total.assign(region="Total")], ignore_index=True)
    df["valid_share"] = (df["nv"] / df["nb"]).round(4)
    df["fsc"] = (df["s"] / df["nv"]).where(df["nv"] > 0).round(4)
    df["missing"] = df["valid_share"].isna() | (df["valid_share"] < MIN_VALID_SHARE)
    df.loc[df["missing"], "fsc"] = np.nan
    return (
        df[["date", "region", "fsc", "valid_share", "missing"]]
        .sort_values(["region", "date"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------- comparison and rule


def in_seasons(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates)
    keep = pd.Series(False, index=dates.index)
    for s, e in OVERLAP_SEASONS:
        keep |= d.between(s, e)
    return keep


def compare(candidate: pd.DataFrame, modis: pd.DataFrame) -> dict:
    """Correlation, mean absolute difference and the linear correction, on days where both
    are valid in the overlap seasons. Pooled over the three cantons, and per region."""
    m = modis[modis["band_m"] == 1800][["date", "region", "fsc"]]
    m = m.assign(date=pd.to_datetime(m["date"]))
    c = candidate[["date", "region", "fsc"]].assign(date=lambda x: pd.to_datetime(x["date"]))
    j = m.merge(c, on=["date", "region"], suffixes=("_modis", "_cand")).dropna()
    j = j[in_seasons(j["date"]) & j["region"].isin([*REGIONS3, "Total"])]
    out = {"per_region": {}}
    for r, g in j.groupby("region"):
        b, a = np.polyfit(g["fsc_cand"], g["fsc_modis"], 1)
        out["per_region"][r] = {
            "n_days": len(g),
            "corr": round(float(g["fsc_modis"].corr(g["fsc_cand"])), 4),
            "mad": round(float((g["fsc_modis"] - g["fsc_cand"]).abs().mean()), 4),
            "fit_a": round(float(a), 4),
            "fit_b": round(float(b), 4),
        }
    p = j[j["region"].isin(REGIONS3)]
    out["pooled_three_cantons"] = {
        "n": len(p),
        "corr": round(float(p["fsc_modis"].corr(p["fsc_cand"])), 4) if len(p) > 2 else None,
        "mad": round(float((p["fsc_modis"] - p["fsc_cand"]).abs().mean()), 4) if len(p) else None,
    }
    return out


def select(results: dict[str, dict]) -> dict:
    """Apply the fixed rule. results: name -> {"corr", "mad", "lag_days"}; None = not built.

    The correlation used is the lowest of the three cantons, so a candidate must track
    MODIS in every region, not only on average.
    """
    rows = {}
    for name, r in results.items():
        if r is None or r.get("corr") is None:
            rows[name] = {**(r or {}), "eligible": False, "why": "not built"}
            continue
        why = []
        if r["corr"] < MIN_CORR:
            why.append(f"correlation {r['corr']:.3f} < {MIN_CORR}")
        if r["lag_days"] is None or r["lag_days"] > MAX_LAG_DAYS:
            why.append(f"publication lag {r['lag_days']} days > {MAX_LAG_DAYS}")
        rows[name] = {**r, "eligible": not why, "why": "; ".join(why) or "eligible"}
    ok = {k: v for k, v in rows.items() if v["eligible"]}
    chosen = min(ok, key=lambda k: ok[k]["mad"]) if ok else None
    return {"candidates": rows, "chosen": chosen}


def apply_fallback(
    modis: pd.DataFrame, fallback: pd.DataFrame | None, fit: dict | None, days: pd.DatetimeIndex
) -> pd.DataFrame:
    """Tracker series per region and day, with source modis, fallback or missing.

    A day uses the corrected fallback only if MODIS has no valid value on that day and the
    previous SWITCH_DAYS - 1 days. Days after the last MODIS row count as not valid.
    """
    m = modis[modis["band_m"] == 1800][["date", "region", "fsc"]].copy()
    m["date"] = pd.to_datetime(m["date"])
    out = []
    for r in [*REGIONS3, "Total"]:
        s = m[m["region"] == r].set_index("date")["fsc"].reindex(days)
        valid = s.notna()
        run = (~valid).astype(int).groupby(valid.cumsum()).cumsum()
        use_fb = run >= SWITCH_DAYS
        val, src = s.copy(), pd.Series(np.where(valid, "modis", "missing"), index=days)
        if fallback is not None and fit is not None and use_fb.any():
            f = fallback[fallback["region"] == r].copy()
            f["date"] = pd.to_datetime(f["date"])
            fb = f.set_index("date")["fsc"].reindex(days)
            corr = (fit[r]["fit_a"] + fit[r]["fit_b"] * fb).clip(0, 1)
            take = use_fb & corr.notna()
            val[take] = corr[take]
            src[take] = "fallback"
        out.append(
            pd.DataFrame({"date": days, "region": r, "fsc": val.values, "source": src.values})
        )
    return pd.concat(out, ignore_index=True)
