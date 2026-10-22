"""Water balance figures (post-hoc diagnostic), from committed data/processed/water_balance/.

release_vs_price.png also needs the local ENTSO-E weekly price cache (data/interim/, never
committed); without it that figure is skipped and the committed PNG is kept.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config
from alpinehydro import water_balance as wb
from alpinehydro.plots import (
    BAND_RANGE,
    CURRENT,
    INK,
    INK_2,
    MEDIAN,
    SURFACE,
    _save,
    _style,
    plt,
)

WB_CREDIT = (
    "Post-hoc diagnostic. Storage and generation: Swiss Federal Office of Energy SFOE (ogd17, "
    "ogd104 Speicherkraft); pumping: SFOE ogd35 monthly, spread evenly over days. eta = 0.75."
)
PRICE_CREDIT = "Prices: Source: ENTSO-E Transparency Platform (local cache, not in this repo)."
COMPARE = "#52514e"  # 2022, dashed, ink-secondary so 2026 stays the one colour
SKIP_NOTE = "release_vs_price skipped: needs local ENTSO-E prices"


def paths_by_week(w: pd.DataFrame, year: int, end: str = "sep") -> pd.DataFrame:
    """Cumulative dS, inflow and release from the window start, one row per week."""
    start, stop = wb.window(year, end)
    f = wb.with_flows(wb.window_weeks(w, start, stop))
    out = f[["ds_gwh", "inflow_gwh", "release_gwh"]].cumsum()
    out.index = pd.RangeIndex(1, len(out) + 1, name="week")
    return out


def water_balance_2026(out_dir: Path = config.FIGURES) -> list[Path]:
    w = wb.load_weekly()
    kept, _ = wb.baseline_years(w, "sep")
    sep_mean, _ = wb.september_pumping_baseline(kept)
    w26 = wb.with_september_pumping(w, 2026, sep_mean)
    base = {y: paths_by_week(w, y) for y in kept}
    n = min(len(p) for p in base.values())
    p26, p22 = paths_by_week(w26, 2026), paths_by_week(w, 2022)
    aug_weeks = len(wb.window_weeks(w, *wb.window(2026, "aug")))

    panels = [
        ("inflow_gwh", "Implied inflow"),
        ("release_gwh", "Release (generation minus 0.75 x pumping)"),
        ("ds_gwh", "Storage change"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), dpi=150, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, (col, title) in zip(axes, panels, strict=True):
        b = pd.DataFrame({y: p[col].iloc[:n].to_numpy() for y, p in base.items()})
        x = np.arange(1, n + 1)
        ax.fill_between(
            x,
            b.min(axis=1),
            b.max(axis=1),
            color=BAND_RANGE,
            lw=0,
            label=f"{min(kept)} to {max(kept)} range",
        )
        ax.plot(x, b.mean(axis=1), color=MEDIAN, lw=1.5, label=f"{min(kept)} to {max(kept)} mean")
        ax.plot(p22.index[:n], p22[col].iloc[:n], color=COMPARE, lw=1.6, ls="--", label="2022")
        ax.plot(
            p26.index[:aug_weeks], p26[col].iloc[:aug_weeks], color=CURRENT, lw=2.2, label="2026"
        )
        ax.plot(
            p26.index[aug_weeks - 1 :],
            p26[col].iloc[aug_weeks - 1 :],
            color=CURRENT,
            lw=2.2,
            ls=":",
            label="2026, September provisional",
        )
        ax.set_title(title, loc="left", color=INK, fontsize=10)
        ticks = [1, 5, 9, 14, 18, 22, n]
        labels = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "27 Sep"]
        ax.set_xticks(ticks[: len(labels)], labels, fontsize=8)
        ax.set_xlim(1, n)
        _style(ax)
    axes[0].set_ylabel("Cumulative GWh since the last Sunday of March", color=INK_2)
    axes[0].legend(loc="upper left", frameon=False, fontsize=7.5, labelcolor=INK_2)
    fig.suptitle(
        "Water balance, April to September (post-hoc): 2026 had far less water, "
        "and operators released less, not more",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11.5,
    )
    fig.text(
        0.01,
        0.01,
        WB_CREDIT + " September 2026 pumping set to the 2015 to 2025 "
        "September mean until SFOE publishes it.",
        color=INK_2,
        fontsize=6,
        wrap=True,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return _save(fig, out_dir, "water_balance_2026")


def year_anomalies(w: pd.DataFrame, end: str = "aug", eta: float = wb.ETA) -> pd.DataFrame:
    """Each year's cumulative anomalies against the 2015 to 2025 mean (display only)."""
    years = [y for y in range(2015, 2027) if wb.cumulative(w, *wb.window(y, end), eta)]
    c = pd.DataFrame({y: wb.cumulative(w, *wb.window(y, end), eta) for y in years}).T
    kept, _ = wb.baseline_years(w, end)
    mean = c.loc[kept, ["ds_gwh", "inflow_gwh", "release_gwh"]].mean()
    return c[["ds_gwh", "inflow_gwh", "release_gwh"]] - mean


def water_balance_years(out_dir: Path = config.FIGURES) -> list[Path]:
    a = year_anomalies(wb.load_weekly())
    fig, ax = plt.subplots(figsize=(7.6, 6.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    lim = 1.15 * float(np.abs(a[["inflow_gwh", "release_gwh"]].to_numpy()).max())
    xs = np.array([-lim, lim])
    for c in (-1000, -500, 0, 500, 1000):
        ax.plot(xs, xs - c, color=INK_2 if c == 0 else "#c9c8c2", lw=0.8 if c else 1.1, zorder=1)
        x0 = 0.45 * lim
        ax.text(
            x0,
            x0 - c + 60,
            "storage anomaly 0" if c == 0 else f"storage {c:+,} GWh",
            color=INK_2,
            fontsize=7,
            rotation=45,
            rotation_mode="anchor",
        )
    for y, r in a.iterrows():
        color = CURRENT if y == 2026 else (INK if y == 2022 else MEDIAN)
        ax.scatter(
            r["inflow_gwh"],
            r["release_gwh"],
            s=46,
            color=color,
            zorder=3,
            edgecolor=SURFACE,
            linewidth=1.5,
        )
        left = y in (2016,)  # label below the dot, clear of 2018 and 2020
        ax.annotate(
            str(y),
            (r["inflow_gwh"], r["release_gwh"]),
            xytext=(4, -13) if left else (6, 4),
            textcoords="offset points",
            color=INK,
            fontsize=8.5,
        )
    ax.axhline(0, color="#c9c8c2", lw=0.8, zorder=0)
    ax.axvline(0, color="#c9c8c2", lw=0.8, zorder=0)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("Inflow anomaly, GWh (right = more water came in)", color=INK_2)
    ax.set_ylabel("Release anomaly, GWh (up = operators took out more)", color=INK_2)
    ax.set_title(
        "Each refill season (last Sunday of March to last Sunday of August)\n"
        "against the 2015 to 2025 mean. Post-hoc.",
        loc="left",
        color=INK,
        fontsize=10.5,
    )
    _style(ax)
    fig.text(
        0.01,
        0.01,
        "Diagonals: equal storage-change anomaly (inflow minus release). " + WB_CREDIT,
        color=INK_2,
        fontsize=6,
        wrap=True,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, out_dir, "water_balance_years")


def release_vs_price_table(w: pd.DataFrame, prices: pd.Series) -> pd.DataFrame:
    """Weekly release anomaly (vs the 2015 to 2025 mean of the same ISO week), April to Sept."""
    f = wb.with_flows(w)
    f = f[~f["gap"] & f["release_gwh"].notna() & f.index.month.isin(range(4, 10))]
    f = f.assign(year=f.index.year, iso=np.minimum(f.index.isocalendar().week.to_numpy(), 52))
    kept, _ = wb.baseline_years(w, "aug")
    norm = f[f["year"].isin(kept)].groupby("iso")["release_gwh"].mean()
    f["release_anom_gwh"] = f["release_gwh"] - f["iso"].map(norm)
    f["price"] = prices.reindex(f.index)
    return f.dropna(subset=["price"])[["year", "release_anom_gwh", "price"]]


def release_vs_price(out_dir: Path = config.FIGURES) -> list[Path]:
    t = release_vs_price_table(wb.load_weekly(), wb.load_prices())
    years = sorted(t["year"].unique())
    cmap = plt.get_cmap("Blues")
    fig, ax = plt.subplots(figsize=(8.6, 5.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    for i, y in enumerate(years):
        part = t[t["year"] == y]
        color = CURRENT if y == 2026 else cmap(0.3 + 0.65 * i / max(len(years) - 1, 1))
        ax.scatter(
            part["price"],
            part["release_anom_gwh"],
            s=26 if y != 2026 else 40,
            color=color,
            edgecolor=SURFACE,
            linewidth=0.8,
            label=str(y),
            zorder=3 if y == 2026 else 2,
        )
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.set_xlabel("Weekly mean CH day-ahead price, EUR/MWh", color=INK_2)
    ax.set_ylabel("Weekly release anomaly, GWh", color=INK_2)
    ax.set_title(
        "Descriptive only: weekly release anomaly against the Swiss price, "
        "April to September (post-hoc)",
        loc="left",
        color=INK,
        fontsize=10.5,
    )
    ax.legend(ncol=2, frameon=False, fontsize=7.5, labelcolor=INK_2, loc="upper right")
    _style(ax)
    fig.text(
        0.01,
        0.01,
        "Descriptive. No conclusion about causes is drawn from this chart. "
        "2026 to 30 August. " + WB_CREDIT + " " + PRICE_CREDIT,
        color=INK_2,
        fontsize=6,
        wrap=True,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, out_dir, "release_vs_price")


def all_figures(out_dir: Path = config.FIGURES, log=print) -> list[Path]:
    paths = water_balance_2026(out_dir) + water_balance_years(out_dir)
    if wb.PRICE_CACHE.exists():
        paths += release_vs_price(out_dir)
    else:
        log(SKIP_NOTE)
    return paths
