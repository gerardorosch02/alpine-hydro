"""Past-only seasonal norms of reservoir fill.

The norm for ISO year Y and ISO week w is the median fill of week w in the
years Y-N to Y-1. It never uses year Y or later, so it is known at the same
time as the observation itself. A norm is only defined when all N past years
are present.

ISO week 53 occurs in some years only. A week-53 reading is compared with the
week-52 norm, and week-53 values never enter any norm.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_iso_week(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    iso = out["valid_time"].dt.isocalendar()
    out["iso_year"] = iso["year"].astype(int)
    out["iso_week"] = iso["week"].astype(int)
    out["week_key"] = out["iso_week"].clip(upper=52)
    return out


def past_median_norm(df: pd.DataFrame, window_years: int) -> pd.Series:
    """Median fill of the same ISO week over the previous window_years years.

    df must hold one region, with columns valid_time and fill.
    Returns a Series aligned with df.index.
    """
    d = add_iso_week(df)
    base = d[d["iso_week"] <= 52].pivot_table(
        index="iso_year", columns="iso_week", values="fill", aggfunc="first"
    )
    norms = np.full(len(d), np.nan)
    for i, (year, key) in enumerate(zip(d["iso_year"], d["week_key"], strict=True)):
        if key not in base.columns:
            continue
        past = base.loc[(base.index >= year - window_years) & (base.index <= year - 1), key]
        past = past.dropna()
        if len(past) == window_years:
            norms[i] = float(np.median(past.to_numpy()))
    return pd.Series(norms, index=df.index, name=f"norm_{window_years}y")


def add_norms(df: pd.DataFrame, windows: tuple[int, ...] = (10, 20)) -> pd.DataFrame:
    """Add norm and deviation (percentage points) columns for each region."""
    parts = []
    for _, g in df.groupby("region", sort=False):
        g = g.sort_values("valid_time").copy()
        for n in windows:
            g[f"norm_{n}y"] = past_median_norm(g, n)
            g[f"dev_{n}y_pp"] = (g["fill"] - g[f"norm_{n}y"]) * 100.0
        parts.append(g)
    return add_iso_week(pd.concat(parts)).sort_values(["region", "valid_time"])
