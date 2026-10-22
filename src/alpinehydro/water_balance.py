"""Weekly water balance of Swiss storage (post-hoc diagnostic, prereg/WATER_BALANCE_PLAN.md).

    implied inflow I = dS + G - eta * P
    release        R = G - eta * P

dS from SFOE TotalCH. G is storage plus pumped-storage generation: by default SFOE ogd104
daily "Speicherkraft" (deviation V1, after the kill criterion triggered on ENTSO-E); with
source="entsoe", ENTSO-E B12 + B10 (the secondary "partial fleet" result). P is SFOE ogd35
monthly pumping spread evenly over days. Everything is in GWh per SFOE week (Monday 00:00 to
Sunday 24:00 Europe/Zurich, valid_time = the Sunday).

build_tables() needs the cached raw data; everything else reads the committed derived
tables in data/processed/water_balance/, so the figures and the decomposition run
without keys.
"""

from __future__ import annotations

import pandas as pd

from alpinehydro import config

OUT_DIR = config.PROCESSED / "water_balance"
WEEKLY = OUT_DIR / "weekly.csv"
MONTHLY = OUT_DIR / "monthly_sfoe.csv"
PRICES = OUT_DIR / "weekly_ch_price.csv"

ETA = 0.75
ETAS = (0.70, 0.75, 0.80)
BASELINE_YEARS = tuple(range(2015, 2026))  # a year with a gap week drops out (2015 for ENTSO-E)
SHARE_CUT = 2 / 3
CREDIT = "Source: ENTSO-E Transparency Platform. Source: Swiss Federal Office of Energy SFOE"


# ---------------------------------------------------------------- building (needs raw data)


def build_tables() -> dict[str, int]:
    """Write the derived weekly and monthly tables from cached ENTSO-E and SFOE data."""
    from alpinehydro.fetch import entsoe, sfoe, sfoe_daily

    st = sfoe.load_processed()
    ch = st[st["region"] == "TotalCH"].set_index("valid_time").sort_index()
    weeks = pd.DataFrame(index=ch.index)
    weeks["content_gwh"] = ch["content_gwh"]
    weeks["max_gwh"] = ch["max_gwh"]
    weeks["ds_gwh"] = ch["content_gwh"].diff()

    for col, name in (("g_res_gwh", "ch_hydro_reservoir"), ("g_ps_gwh", "ch_hydro_pumped")):
        w = entsoe.sfoe_weeks_gwh(entsoe.generation_hourly(name))
        w.index = pd.to_datetime(w.index)
        weeks[col] = w["gwh"].reindex(weeks.index)
        weeks[col.replace("_gwh", "_hours_share")] = w["share"].reindex(weeks.index).fillna(0.0)
    weeks["entsoe_gap"] = weeks[["g_res_gwh", "g_ps_gwh"]].isna().any(axis=1)

    monthly = sfoe_daily.monthly_balance()
    pump = sfoe_daily.sfoe_weeks(sfoe_daily.daily_pumping(monthly))
    weeks["pumping_gwh"] = pump["gwh"].reindex(weeks.index)
    prod = sfoe_daily.sfoe_weeks(sfoe_daily.daily_storage_production())
    weeks["sfoe_speicherkraft_gwh"] = prod["gwh"].reindex(weeks.index)

    weeks = weeks[weeks.index >= pd.Timestamp("2015-01-04")]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write(weeks.round(3), WEEKLY, "weekly")

    m = monthly[monthly.index >= pd.Timestamp("2015-01-01")].copy()
    m["content_end_gwh"] = month_end_content(ch["content_gwh"], m.index)
    for col, name in (
        ("entsoe_res_gwh", "ch_hydro_reservoir"),
        ("entsoe_ps_gwh", "ch_hydro_pumped"),
    ):
        m[col] = _monthly_gwh(entsoe.generation_hourly(name)).reindex(m.index)
    _write(m.round(3), MONTHLY, "monthly")
    return {"weeks": len(weeks), "months": len(m)}


def build_prices() -> int:
    """Weekly mean CH day-ahead price per SFOE week (descriptive scatter only)."""
    w = pd.read_parquet(config.INTERIM / "entsoe_prices_weekly.parquet")
    w = w[(w["zone"] == "CH") & w["complete"]]
    out = pd.DataFrame(
        {"ch_da_eur_mwh": w["baseload"].round(2).to_numpy()},
        index=pd.DatetimeIndex(pd.to_datetime(w["valid_time"]).to_numpy(), name="valid_time"),
    )
    _write(out, PRICES, "weekly price")
    return len(out)


def _monthly_gwh(hourly_mw: pd.Series, min_share: float = 0.90) -> pd.Series:
    naive = hourly_mw.index.tz_localize(None)
    month = naive.to_period("M").to_timestamp()
    g = hourly_mw.groupby(month)
    mean, n = g.mean(), g.count()
    hours = pd.Series(
        [
            (
                pd.Timestamp(mo, tz="Europe/Zurich")
                + pd.offsets.MonthBegin(1)
                - pd.Timestamp(mo, tz="Europe/Zurich")
            )
            / pd.Timedelta(hours=1)
            for mo in mean.index
        ],
        index=mean.index,
    )
    return (mean * hours / 1000.0).where(n / hours >= min_share)


def month_end_content(content: pd.Series, months: pd.DatetimeIndex) -> pd.Series:
    """Content at 24:00 on the last day of each month, linear in time between Sundays."""
    import numpy as np

    ends = (months + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)).asi8  # 24:00 = next 00:00
    t = (content.index + pd.Timedelta(days=1)).asi8  # Sunday 24:00
    vals = np.interp(ends, t, content.to_numpy(dtype=float))
    vals[(ends < t[0]) | (ends > t[-1])] = np.nan
    return pd.Series(vals, index=months)


def _write(df: pd.DataFrame, path, what: str) -> None:
    header = (
        f"# water balance {what} table (post-hoc, prereg/WATER_BALANCE_PLAN.md)\n"
        f"# {CREDIT}\n"
        "# derived aggregates in GWh only; no raw ENTSO-E data; removed on request\n"
    )
    out = df.copy()
    out.index = out.index.strftime("%Y-%m-%d")
    path.write_text(header + out.to_csv(lineterminator="\n"), encoding="utf-8")


# ---------------------------------------------------------------- reading and the identity


def load_weekly(source: str = "sfoe") -> pd.DataFrame:
    return use_source(pd.read_csv(WEEKLY, comment="#", index_col=0, parse_dates=[0]), source)


def use_source(w: pd.DataFrame, source: str = "sfoe") -> pd.DataFrame:
    """Set g_gwh and gap from SFOE ogd104 (primary, V1) or ENTSO-E B12 + B10 (V4)."""
    out = w.copy()
    if source == "sfoe":
        out["g_gwh"] = w["sfoe_speicherkraft_gwh"]
        out["gap"] = out["g_gwh"].isna()
    elif source == "entsoe":
        out["g_gwh"] = w["g_res_gwh"] + w["g_ps_gwh"]
        out["gap"] = w["entsoe_gap"].astype(bool) | out["g_gwh"].isna()
    else:
        raise ValueError(source)
    out.attrs["source"] = source
    return out


def load_monthly() -> pd.DataFrame:
    return pd.read_csv(MONTHLY, comment="#", index_col=0, parse_dates=[0])


def load_prices() -> pd.DataFrame:
    return pd.read_csv(PRICES, comment="#", index_col=0, parse_dates=[0])


def release(w: pd.DataFrame, eta: float = ETA) -> pd.Series:
    return w["g_gwh"] - eta * w["pumping_gwh"]


def inflow(w: pd.DataFrame, eta: float = ETA) -> pd.Series:
    return w["ds_gwh"] + release(w, eta)


def with_flows(w: pd.DataFrame, eta: float = ETA) -> pd.DataFrame:
    out = w.copy()
    out["release_gwh"] = release(w, eta)
    out["inflow_gwh"] = inflow(w, eta)
    return out


# ---------------------------------------------------------------- windows


def last_sunday_on_or_before(day: pd.Timestamp) -> pd.Timestamp:
    return day - pd.Timedelta(days=(day.dayofweek + 1) % 7)


def window(year: int, end: str = "aug") -> tuple[pd.Timestamp, pd.Timestamp]:
    """(start reading, end reading) Sundays. end 'aug' = primary, 'sep' = update window."""
    start = last_sunday_on_or_before(pd.Timestamp(f"{year}-03-31"))
    last = pd.Timestamp(f"{year}-08-31") if end == "aug" else pd.Timestamp(f"{year}-09-30")
    return start, last_sunday_on_or_before(last)


def window_weeks(w: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return w[(w.index > start) & (w.index <= end)]


def cumulative(w: pd.DataFrame, start, end, eta: float = ETA) -> dict | None:
    """Cumulative dS, I and R over a window, or None if any week has a gap."""
    part = window_weeks(w, start, end)
    if part.empty or part["gap"].any() or part[["ds_gwh", "pumping_gwh"]].isna().any().any():
        return None
    f = with_flows(part, eta)
    return {
        "ds_gwh": float(f["ds_gwh"].sum()),
        "inflow_gwh": float(f["inflow_gwh"].sum()),
        "release_gwh": float(f["release_gwh"].sum()),
        "weeks": int(len(f)),
    }


def baseline_years(w: pd.DataFrame, end: str = "aug") -> tuple[list[int], list[int]]:
    """(kept, dropped) baseline years under the gap-week rule."""
    kept, dropped = [], []
    for y in BASELINE_YEARS:
        (kept if cumulative(w, *window(y, end)) is not None else dropped).append(y)
    return kept, dropped


# ---------------------------------------------------------------- decomposition (plan section 4)


def label_for(inflow_share: float | None, release_share: float | None) -> str:
    if inflow_share is None:
        return "no shortfall"
    if inflow_share >= SHARE_CUT:
        return "weather story"
    if release_share >= SHARE_CUT:
        return "operator story"
    return "mixed"


def decompose(w: pd.DataFrame, year: int, end: str = "aug", eta: float = ETA) -> dict:
    """Cumulative anomalies of one year against the mean of the other baseline years."""
    kept, _ = baseline_years(w, end)
    base_years = [y for y in kept if y != year]
    base = pd.DataFrame({y: cumulative(w, *window(y, end), eta) for y in base_years}).T
    this = cumulative(w, *window(year, end), eta)
    if this is None:
        raise ValueError(f"{year} window has a gap week or missing data")
    mean = base[["ds_gwh", "inflow_gwh", "release_gwh"]].mean()
    a_s = this["ds_gwh"] - mean["ds_gwh"]
    a_i = this["inflow_gwh"] - mean["inflow_gwh"]
    a_r = this["release_gwh"] - mean["release_gwh"]
    inflow_share = release_share = None
    if a_s < 0:
        inflow_share, release_share = -a_i / -a_s, a_r / -a_s
    start, stop = window(year, end)
    return {
        "year": year,
        "window": f"{start.date()} to {stop.date()}",
        "eta": eta,
        "baseline_years": base_years,
        "this": {k: round(v, 1) for k, v in this.items() if k != "weeks"},
        "baseline_mean": {k: round(float(v), 1) for k, v in mean.items()},
        "baseline_min": {k: round(float(v), 1) for k, v in base[mean.index].min().items()},
        "baseline_max": {k: round(float(v), 1) for k, v in base[mean.index].max().items()},
        "anomaly": {
            "ds_gwh": round(a_s, 1),
            "inflow_gwh": round(a_i, 1),
            "release_gwh": round(a_r, 1),
        },
        "inflow_share": None if inflow_share is None else round(inflow_share, 3),
        "release_share": None if release_share is None else round(release_share, 3),
        "label": label_for(inflow_share, release_share),
        "weeks": this["weeks"],
    }


def with_september_pumping(w: pd.DataFrame, year: int, gwh: float) -> pd.DataFrame:
    """Secondary (a): set the missing September pumping of `year` to a monthly total."""
    from alpinehydro.fetch import sfoe_daily

    m = load_monthly()[["pumping_gwh"]].copy()
    m.loc[pd.Timestamp(f"{year}-09-01"), "pumping_gwh"] = gwh
    pump = sfoe_daily.sfoe_weeks(sfoe_daily.daily_pumping(m.sort_index()))
    out = w.copy()
    out["pumping_gwh"] = pump["gwh"].reindex(out.index)
    return out


def september_pumping_baseline(years) -> tuple[float, float]:
    m = load_monthly()
    sep = m[(m.index.month == 9) & m.index.year.isin(list(years))]["pumping_gwh"]
    return float(sep.mean()), float(sep.std(ddof=1))


def decompose_monthly_sfoe(year: int, eta: float = ETA, months=range(4, 9)) -> dict:
    """Secondary (b): all-SFOE monthly balance, April to August, against other baseline years."""
    m = load_monthly()
    m = m.assign(ds_gwh=m["content_end_gwh"].diff())

    def cum(y):
        part = m[(m.index.year == y) & m.index.month.isin(list(months))]
        if (
            len(part) != len(months)
            or part[["ds_gwh", "gen_storage_gwh", "pumping_gwh"]].isna().any().any()
        ):
            return None
        r = part["gen_storage_gwh"] - eta * part["pumping_gwh"]
        return {
            "ds_gwh": float(part["ds_gwh"].sum()),
            "inflow_gwh": float((part["ds_gwh"] + r).sum()),
            "release_gwh": float(r.sum()),
            "provisional": bool((~part["definitive"].astype(bool)).any()),
        }

    base_years = [y for y in range(2016, 2026) if y != year and cum(y) is not None]
    base = pd.DataFrame({y: cum(y) for y in base_years}).T
    mean = base[["ds_gwh", "inflow_gwh", "release_gwh"]].astype(float).mean()
    this = cum(year)
    a_s = this["ds_gwh"] - mean["ds_gwh"]
    a_i = this["inflow_gwh"] - mean["inflow_gwh"]
    a_r = this["release_gwh"] - mean["release_gwh"]
    i_sh = r_sh = None
    if a_s < 0:
        i_sh, r_sh = -a_i / -a_s, a_r / -a_s
    return {
        "year": year,
        "eta": eta,
        "baseline_years": base_years,
        "provisional": this["provisional"],
        "anomaly": {
            "ds_gwh": round(a_s, 1),
            "inflow_gwh": round(a_i, 1),
            "release_gwh": round(a_r, 1),
        },
        "inflow_share": None if i_sh is None else round(i_sh, 3),
        "release_share": None if r_sh is None else round(r_sh, 3),
        "label_cross_check": label_for(i_sh, r_sh),
    }


# ---------------------------------------------------------------- snow forecast link (section 5)


def snow_link(w: pd.DataFrame, eta: float = ETA) -> dict:
    """H3a 2026 forecast against 'actual water, normal operators' (needs September pumping)."""
    feats = pd.read_csv(config.PROCESSED / "snow" / "features_h3.csv", comment="#")
    row = feats[
        (feats["year"] == 2026)
        & (feats["issue"] == "may1")
        & (feats["region"] == "Total")
        & (feats["band_m"] == 1800)
    ].iloc[0]
    start = pd.Timestamp(row["start_valid_time"])
    end = pd.Timestamp("2026-09-27")
    import json

    fc_total = json.loads((config.REPORTS / "checks" / "h3_results.json").read_text())["case_2026"][
        "full"
    ]
    cap = float(w.loc[end, "max_gwh"])
    fill_start = 100 * float(w.loc[start, "content_gwh"]) / float(w.loc[start, "max_gwh"])
    forecast_fill = fill_start + (fc_total - float(row["start_fill_pp"]))
    actual_fill = 100 * float(w.loc[end, "content_gwh"]) / cap

    f = with_flows(w, eta)
    sel = (f.index > start) & (f.index <= end)
    inflow_2026 = float(f.loc[sel, "inflow_gwh"].sum())
    weeks_of_year = [(d.month, d.day) for d in f.index[sel]]
    kept, _ = baseline_years(w, "sep")
    rel = []
    for y in kept:
        s_y = start.replace(year=y)
        s_y = last_sunday_on_or_before(s_y)
        e_y = s_y + (end - start)
        part = f[(f.index > s_y) & (f.index <= e_y)]
        rel.append(float(part["release_gwh"].sum()))
    base_release = float(pd.Series(rel).mean())
    cf_content = float(w.loc[start, "content_gwh"]) + inflow_2026 - base_release
    cf_fill = 100 * cf_content / cap
    miss = forecast_fill - actual_fill
    return {
        "eta": eta,
        "start_week": str(start.date()),
        "end_week": str(end.date()),
        "weeks": len(weeks_of_year),
        "h3a_total_forecast_fill": fc_total,
        "forecast_national_fill": round(forecast_fill, 1),
        "water_normal_operators_fill": round(cf_fill, 1),
        "actual_national_fill": round(actual_fill, 1),
        "forecast_miss_pp": round(miss, 1),
        "share_of_miss_water": round((forecast_fill - cf_fill) / miss, 3),
        "share_of_miss_release": round((cf_fill - actual_fill) / miss, 3),
        "baseline_years": kept,
        "gwh_per_pp": round(cap / 100, 1),
    }
