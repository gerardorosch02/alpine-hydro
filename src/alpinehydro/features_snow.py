"""Part C features and targets, exactly as `prereg/H3_ANALYSIS_PLAN.md` (tag v0.2-h3plan).

One row per year, issue date (1 April, 1 May), region and elevation band:

- `modis_fsc`: mean daily FSC over the 8 days ending at the issue date minus 3 days.
- `era5_swe`: mean daily SWE (mm) over the 8 days ending at the issue date minus 7 days.
- `era5_anom10`: robustness only, `era5_swe` minus the mean of the same 8 calendar days in
  each of the previous 10 years.
- `start_fill_pp`: SFOE fill of the latest week with known_time at or before the issue
  date 23:59 Europe/Zurich.
- Targets: `end_fill_pp` (last Sunday of September) and `refill_gwh` (that week's content
  minus the lowest weekly content with a valid Sunday from 1 February to 31 May).
- `c0_fill_pp`, `c0_refill_gwh`: the mean of the target over the previous 10 years.
- `norm10_end_pp`: the past-only 10-year median fill of the same ISO week (norms.py), used
  by H3b.

Every input carries its latest date (`*_last`, `*_base_last_year`), so tests can check
the timing. Only SFOE and snow inputs are used, so the table is committed.
The H3b target (October to December CH minus DE-LU spread) is one number per year.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alpinehydro import norms, snow

TZ = "Europe/Zurich"
ISSUES = {"apr1": (4, 1), "may1": (5, 1)}
MODIS_LAG_DAYS = 3
ERA5_LAG_DAYS = 7
WINDOW_DAYS = 8
MIN_DAYS = 4
BASE_YEARS = 10
FIRST_YEAR, LAST_YEAR = 2001, 2026
H3B_YEARS = range(2015, 2026)
OUT = snow.SNOW_DIR / "features_h3.csv"
Q4_OUT = snow.SNOW_DIR / "h3b_q4_spread.csv"
MODIS_CSV = snow.SNOW_DIR / "modis_daily.csv"
ERA5_CSV = snow.SNOW_DIR / "era5land_swe_daily.csv"


def cutoff(issue: pd.Timestamp, lag_days: int) -> pd.Timestamp:
    return issue - pd.Timedelta(days=lag_days)


def window_mean(daily: pd.Series, end: pd.Timestamp) -> tuple[float, int, pd.Timestamp | None]:
    """Mean over the 8 days ending at `end` (inclusive), skipping missing days.

    Returns (mean, days present, latest day used). The mean is NaN with fewer than 4 days.
    """
    w = daily.loc[end - pd.Timedelta(days=WINDOW_DAYS - 1) : end].dropna()
    last = w.index.max() if len(w) else None
    if len(w) < MIN_DAYS:
        return np.nan, len(w), last
    return float(w.mean()), len(w), last


def alpine_total(storage: pd.DataFrame) -> pd.DataFrame:
    """Add region 'Total': the sum of Wallis, Graubuenden and Tessin."""
    st = storage[storage["region"].isin(snow.CANTONS)]
    tot = st.groupby(["valid_time", "known_time"], as_index=False)[["content_gwh", "max_gwh"]].sum()
    n = st.groupby("valid_time")["region"].nunique()
    tot = tot[tot["valid_time"].map(n) == len(snow.CANTONS)]
    tot["region"] = "Total"
    tot["fill"] = tot["content_gwh"] / tot["max_gwh"]
    return pd.concat([st, tot], ignore_index=True).sort_values(["region", "valid_time"])


def last_sunday_september(year: int) -> pd.Timestamp:
    d = pd.Timestamp(year, 9, 30)
    return d - pd.Timedelta(days=(d.weekday() + 1) % 7)


def starting_storage(st: pd.DataFrame, issue: pd.Timestamp) -> pd.Series | None:
    """Latest week of one region with known_time at or before the issue date 23:59."""
    limit = pd.Timestamp(issue.year, issue.month, issue.day, 23, 59, tz=TZ)
    known = st[pd.to_datetime(st["known_time"], utc=True) <= limit.tz_convert("UTC")]
    return None if known.empty else known.sort_values("valid_time").iloc[-1]


def targets(st: pd.DataFrame, year: int) -> dict:
    """End-of-September fill (pp) and refill (GWh) of one region."""
    end_day = last_sunday_september(year)
    row = st[st["valid_time"] == end_day]
    if row.empty:
        return {"end_valid_time": end_day, "end_fill_pp": np.nan, "refill_gwh": np.nan}
    vt = st["valid_time"]
    spring = st[(vt >= pd.Timestamp(year, 2, 1)) & (vt <= pd.Timestamp(year, 5, 31))]
    low = spring.loc[spring["content_gwh"].idxmin()]
    return {
        "end_valid_time": end_day,
        "end_fill_pp": float(row["fill"].iloc[0]) * 100,
        "end_content_gwh": float(row["content_gwh"].iloc[0]),
        "spring_min_valid_time": low["valid_time"],
        "refill_gwh": float(row["content_gwh"].iloc[0] - low["content_gwh"]),
    }


def _series(df: pd.DataFrame, region: str, band: int, col: str) -> pd.Series:
    d = df[(df["region"] == region) & (df["band_m"] == band)]
    return d.set_index("date")[col].sort_index()


def build(modis: pd.DataFrame, era5: pd.DataFrame, storage: pd.DataFrame) -> pd.DataFrame:
    st_all = alpine_total(storage)
    st_all["valid_time"] = pd.to_datetime(st_all["valid_time"])
    rows = []
    for region in snow.REGIONS:
        st = st_all[st_all["region"] == region].copy()
        st["norm10"] = norms.past_median_norm(st, BASE_YEARS).to_numpy()
        tgt = {y: targets(st, y) for y in range(FIRST_YEAR - BASE_YEARS, LAST_YEAR + 1)}
        for band in snow.BANDS_M:
            fsc = _series(modis, region, band, "fsc")
            swe = _series(era5, region, band, "swe_mm")
            for year in range(FIRST_YEAR, LAST_YEAR + 1):
                past = [y for y in range(year - BASE_YEARS, year) if y in tgt]
                for issue_name, (m, d) in ISSUES.items():
                    issue = pd.Timestamp(year, m, d)
                    r = {
                        "year": year,
                        "issue": issue_name,
                        "issue_date": issue.date(),
                        "region": region,
                        "band_m": band,
                    }
                    c_m, c_e = cutoff(issue, MODIS_LAG_DAYS), cutoff(issue, ERA5_LAG_DAYS)
                    r["modis_cutoff"], r["era5_cutoff"] = c_m.date(), c_e.date()
                    r["modis_fsc"], r["modis_n_days"], last = window_mean(fsc, c_m)
                    r["modis_last"] = last.date() if last is not None else None
                    r["era5_swe"], r["era5_n_days"], last = window_mean(swe, c_e)
                    r["era5_last"] = last.date() if last is not None else None
                    base = []
                    for k in range(year - BASE_YEARS, year):
                        v, _, _ = window_mean(swe, c_e.replace(year=k))
                        base.append(v)
                    r["era5_anom10"] = (
                        r["era5_swe"] - float(np.mean(base))
                        if len(base) == BASE_YEARS and np.isfinite(base).all()
                        else np.nan
                    )
                    r["era5_base_last_year"] = year - 1
                    s0 = starting_storage(st, issue)
                    r["start_fill_pp"] = float(s0["fill"]) * 100 if s0 is not None else np.nan
                    r["start_valid_time"] = s0["valid_time"].date() if s0 is not None else None
                    r["start_known_time"] = s0["known_time"] if s0 is not None else None
                    t = tgt[year]
                    r["end_valid_time"] = t["end_valid_time"].date()
                    r["end_fill_pp"], r["refill_gwh"] = t["end_fill_pp"], t["refill_gwh"]
                    end_rows = st[st["valid_time"] == t["end_valid_time"]]
                    r["norm10_end_pp"] = (
                        float(end_rows["norm10"].iloc[0]) * 100 if len(end_rows) else np.nan
                    )
                    c0 = [tgt[y]["end_fill_pp"] for y in past]
                    c0r = [tgt[y]["refill_gwh"] for y in past]
                    full = len(past) == BASE_YEARS and np.isfinite(c0).all()
                    r["c0_fill_pp"] = float(np.mean(c0)) if full else np.nan
                    r["c0_refill_gwh"] = float(np.mean(c0r)) if full else np.nan
                    r["c0_last_year"] = max(past) if past else None
                    rows.append(r)
    return pd.DataFrame(rows)


def q4_spread() -> pd.DataFrame:
    """Mean daily CH minus DE-LU baseload spread, 1 October to 31 December, per year."""
    from alpinehydro.features import daily_spread

    s = daily_spread("CH", "DE_LU")
    s.index = pd.to_datetime(s.index)
    rows = []
    for y in H3B_YEARS:
        days = pd.date_range(f"{y}-10-01", f"{y}-12-31", freq="D")
        w = s.reindex(days)
        rows.append(
            {
                "year": y,
                "q4_spread_eur_mwh": round(float(w.mean()), 3),
                "days": int(w.notna().sum()),
                "days_expected": len(days),
            }
        )
    return pd.DataFrame(rows)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from alpinehydro.fetch import sfoe

    return snow.read_csv(MODIS_CSV), snow.read_csv(ERA5_CSV), sfoe.load_processed()


def write(features: pd.DataFrame, q4: pd.DataFrame | None = None) -> list:
    paths = [
        snow.write_csv(
            features,
            OUT,
            [
                "Part C features and targets, built by alpinehydro.features_snow",
                "plan: prereg/H3_ANALYSIS_PLAN.md (tag v0.2-h3plan)",
                "snow: NSIDC MOD10A1/MYD10A1 v6.1 and ERA5-Land (C3S); storage: SFOE",
            ],
        )
    ]
    if q4 is not None:
        paths.append(
            snow.write_csv(
                q4,
                Q4_OUT,
                [
                    "H3b target: mean daily CH minus DE-LU day-ahead baseload spread,",
                    "1 October to 31 December, one number per year (no price series).",
                    "Built from cached ENTSO-E Transparency Platform day-ahead prices.",
                ],
            )
        )
    return paths


def load() -> pd.DataFrame:
    df = pd.read_csv(OUT, comment="#")
    return df


def load_q4() -> pd.DataFrame:
    return pd.read_csv(Q4_OUT, comment="#")
