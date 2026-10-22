"""Water balance audit (post-hoc, prereg/WATER_BALANCE_PLAN.md sections 8 and 9).

Reconciles ENTSO-E storage generation with SFOE and applies the kill criterion. It
triggered, so G comes from SFOE ogd104 (deviation V1); the implied-inflow checks use that
G, on weeks up to the end of 2025 only. Nothing here looks at a 2026 or 2022
anomaly. Reads the committed derived tables only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alpinehydro import config
from alpinehydro import water_balance as wb

HPCATCH = config.PROCESSED / "water_balance" / "hpcatch_annual_inflow.csv"
OVERLAP_START = pd.Timestamp("2015-07-01")
COVERAGE_END = pd.Timestamp("2026-09-27")
LAST_SANITY_SUNDAY = pd.Timestamp("2025-12-28")


def _stats(entsoe: pd.Series, sfoe: pd.Series) -> dict:
    j = pd.concat([entsoe.rename("e"), sfoe.rename("s")], axis=1).dropna()
    pct = (j["e"] - j["s"]) / j["s"]
    return {
        "n": int(len(j)),
        "correlation": round(float(j["e"].corr(j["s"])), 4),
        "mean_pct_diff": round(float(pct.mean() * 100), 2),
        "median_ratio": round(float((j["e"] / j["s"]).median()), 4),
        "share_within_10pct": round(float((pct.abs() <= 0.10).mean()), 3),
    }


def reconcile(w: pd.DataFrame, last_week: pd.Timestamp) -> dict:
    part = w[(w.index >= OVERLAP_START + pd.Timedelta(days=6)) & (w.index <= last_week)]
    part = part[~part["entsoe_gap"]]
    e = part["g_res_gwh"] + part["g_ps_gwh"]
    s = part["sfoe_speicherkraft_gwh"]
    out = _stats(e, s)
    out["first_week"] = str(part.index.min().date())
    out["last_week"] = str(part.index.max().date())
    out["by_year"] = {
        int(y): _stats(e[e.index.year == y], s[s.index.year == y])
        for y in sorted(set(part.index.year))
    }
    return out


def reconcile_monthly(m: pd.DataFrame) -> dict:
    m = m[m.index >= pd.Timestamp("2015-07-01")]
    e = m["entsoe_res_gwh"] + m["entsoe_ps_gwh"]
    out = _stats(e, m["gen_storage_gwh"])
    out["by_year"] = {
        int(y): _stats(e[e.index.year == y], m.loc[m.index.year == y, "gen_storage_gwh"])
        for y in sorted(set(m.index.year))
    }
    return out


def reconcile_sfoe_sources(w: pd.DataFrame, m: pd.DataFrame) -> dict:
    """ogd104 weekly Speicherkraft re-summed by month (via the monthly table) against ogd35."""
    from alpinehydro.fetch import sfoe_daily

    d = sfoe_daily.daily_storage_production()
    d = d[d.index < pd.Timestamp("2026-10-01")]
    monthly = d.groupby(d.index.to_period("M").to_timestamp()).sum()
    j = pd.concat([monthly.rename("e"), m["gen_storage_gwh"].rename("s")], axis=1).dropna()
    pct = ((j["e"] - j["s"]) / j["s"]).abs()
    out = _stats(j["e"], j["s"])
    out["share_within_5pct"] = round(float((pct <= 0.05).mean()), 3)
    out["max_abs_pct_2015_2025"] = round(float(pct[pct.index.year <= 2025].max() * 100), 2)
    out["max_abs_pct_2026"] = round(float(pct[pct.index.year == 2026].max() * 100), 2)
    return out


def coverage(w: pd.DataFrame) -> dict:
    part = w[(w.index >= OVERLAP_START + pd.Timedelta(days=6)) & (w.index <= COVERAGE_END)]
    out = {}
    for col in ("g_res_hours_share", "g_ps_hours_share"):
        out[col.replace("_hours_share", "_missing_hours_pct")] = round(
            float((1 - part[col]).mean() * 100), 3
        )
        short = part[part[col] < 1.0]
        out[col.replace("_hours_share", "_weeks_short")] = [
            f"{d.date()} ({s:.3f})" for d, s in short[col].items()
        ]
    out["gap_weeks"] = [str(d.date()) for d in part.index[part["entsoe_gap"]]]
    sf = w[w.index <= COVERAGE_END]["sfoe_speicherkraft_gwh"]
    out["ogd104_first_week"] = str(sf.first_valid_index().date())
    out["ogd104_missing_weeks"] = int(sf.loc[sf.first_valid_index() :].isna().sum())
    for y in (2022, 2026):
        for end in ("aug", "sep"):
            ww = wb.window_weeks(w, *wb.window(y, end))
            out[f"gap_weeks_{y}_{end}"] = int(ww["entsoe_gap"].sum())
    return out


def kill(rec: dict, cov: dict) -> dict:
    reasons = []
    if rec["share_within_10pct"] < 0.5:
        reasons.append("more than half of the overlap weeks differ by more than 10%")
    for k in ("g_res_missing_hours_pct", "g_ps_missing_hours_pct"):
        if cov[k] > 2.0:
            reasons.append(f"{k} above 2%")
    for k in ("gap_weeks_2022_aug", "gap_weeks_2026_aug"):
        if cov[k] > 0:
            reasons.append(f"{k}: {cov[k]}")
    return {"triggered": bool(reasons), "reasons": reasons}


def sanity(w: pd.DataFrame, eta: float = wb.ETA) -> dict:
    f = wb.with_flows(w[(w.index <= LAST_SANITY_SUNDAY) & ~w["gap"]], eta)
    f = f.dropna(subset=["inflow_gwh"])
    summer = f[f.index.month.isin(range(4, 10))]
    base = f[f.index.year.isin(range(2015, 2026))]
    monthly = base.groupby(base.index.month)["inflow_gwh"].mean().round(1)
    annual = {}
    for y in range(2015, 2026):
        start = wb.last_sunday_on_or_before(pd.Timestamp(f"{y - 1}-12-31"))
        end = wb.last_sunday_on_or_before(pd.Timestamp(f"{y}-12-31"))
        c = wb.cumulative(w, start, end, eta)
        annual[y] = None if c is None else round(c["inflow_gwh"], 0)
    vals = [v for v in annual.values() if v is not None]
    return {
        "eta": eta,
        "weeks": int(len(f)),
        "negative_share_all": round(float((f["inflow_gwh"] < 0).mean()), 3),
        "negative_share_apr_sep": round(float((summer["inflow_gwh"] < 0).mean()), 3),
        "mean_weekly_inflow_by_month_2015_2025": {int(k): float(v) for k, v in monthly.items()},
        "peak_month": int(monthly.idxmax()),
        "annual_inflow_gwh": annual,
        "annual_min": min(vals),
        "annual_max": max(vals),
        "annual_mean": round(float(np.mean(vals)), 0),
    }


def hpcatch(annual: dict) -> dict:
    if not HPCATCH.exists():
        return {"accessible": False}
    h = pd.read_csv(HPCATCH, comment="#").set_index("year")["inflow_hm3"]
    years = [y for y in range(2015, 2023) if annual.get(y) is not None and y in h.index]
    a = pd.Series({y: annual[y] for y in years})
    return {
        "accessible": True,
        "years": years,
        "correlation": round(float(a.corr(h.loc[years])), 3),
        "hpcatch_hm3": {y: float(h.loc[y]) for y in years},
    }


def run() -> dict:
    w = wb.load_weekly()
    m = wb.load_monthly()
    last_week = w.index[w["sfoe_speicherkraft_gwh"].notna()].max()
    rec = reconcile(w, last_week)
    cov = coverage(w)
    out = {
        "post_hoc": True,
        "plan": "prereg/WATER_BALANCE_PLAN.md (tag v0.4-waterbalance-plan)",
        "reconcile_weekly_entsoe_vs_ogd104": rec,
        "reconcile_monthly_entsoe_vs_ogd35": reconcile_monthly(m),
        "reconcile_monthly_ogd104_vs_ogd35": reconcile_sfoe_sources(w, m),
        "coverage": cov,
        "kill_criterion": kill(rec, cov),
        "kill_resolution": "G switched to SFOE ogd104 Speicherkraft before any 2026 number (V1)",
        "baseline_years_aug": wb.baseline_years(w, "aug"),
        "baseline_years_aug_entsoe": wb.baseline_years(wb.use_source(w, "entsoe"), "aug"),
    }
    out["sanity"] = {str(eta): sanity(w, eta) for eta in wb.ETAS}
    out["hpcatch"] = hpcatch(out["sanity"][str(wb.ETA)]["annual_inflow_gwh"])
    return out
