"""Part C figures, built from committed data/processed/snow/ files only (no keys)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpinehydro import config, features_snow, snow
from alpinehydro.plots import (
    BAND_IQR,
    BAND_RANGE,
    CURRENT,
    GRID,
    HOLLOW,
    INK,
    INK_2,
    MEDIAN,
    SURFACE,
    _save,
    _style,
    plt,
)

# Categorical slots 1-3 of the reference palette (validated, light surface).
REGION_STYLE = {
    "Wallis": ("#2a78d6", "o"),
    "Graubuenden": ("#eb6834", "s"),
    "Tessin": ("#1baf7a", "^"),
}
C1_COLOR = "#eb6834"
FULL_COLOR = "#2a78d6"
SNOW_CREDIT = (
    "MODIS MOD10A1/MYD10A1 v6.1, NASA NSIDC DAAC. Contains modified Copernicus Climate Change "
    "Service information (ERA5-Land). Outlines: swisstopo. Storage: Swiss Federal Office of "
    "Energy SFOE."
)
SEASON_TICKS = [
    (0, "Oct"),
    (31, "Nov"),
    (61, "Dec"),
    (92, "Jan"),
    (123, "Feb"),
    (151, "Mar"),
    (182, "Apr"),
    (212, "May"),
    (243, "Jun"),
    (272, ""),
]
REGION_LABEL = {
    "Total": "Three regions",
    "Wallis": "Wallis",
    "Graubuenden": "Graubuenden",
    "Tessin": "Tessin",
}


def season_table(modis: pd.DataFrame, band: int = 1800) -> pd.DataFrame:
    """Daily FSC by snow season (1 October to 30 June) and day of season, 29 Feb dropped."""
    d = modis[(modis["band_m"] == band)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[~((d["date"].dt.month == 2) & (d["date"].dt.day == 29))]
    d = d[~d["date"].dt.month.isin([7, 8, 9])]
    d["season"] = np.where(d["date"].dt.month >= 10, d["date"].dt.year, d["date"].dt.year - 1)
    start = pd.to_datetime(d["season"].astype(str) + "-10-01")
    d["doy"] = (d["date"] - start).dt.days
    # Seasons that cross a leap day have one more day after February: remove the shift.
    leap = (d["date"].dt.month <= 6) & (d["date"].dt.month >= 3) & d["date"].dt.is_leap_year
    d.loc[leap, "doy"] -= 1
    return d


def snow_tracker(modis: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    d = season_table(modis)
    cur_season = int(d["season"].max())
    prev = cur_season - 1
    hist = d[(d["season"] >= 2000) & (d["season"] <= 2024)]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.2), dpi=150, sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, region in zip(axes.flat, ["Total", *snow.CANTONS], strict=True):
        h = hist[hist["region"] == region].pivot_table(index="doy", columns="season", values="fsc")
        q = (
            pd.DataFrame(
                {
                    "lo": h.min(axis=1),
                    "q25": h.quantile(0.25, axis=1),
                    "med": h.median(axis=1),
                    "q75": h.quantile(0.75, axis=1),
                    "hi": h.max(axis=1),
                }
            ).sort_index()
            * 100
        )
        ax.fill_between(
            q.index, q["lo"], q["hi"], color=BAND_RANGE, lw=0, label="2000/01 to 2024/25 range"
        )
        ax.fill_between(
            q.index, q["q25"], q["q75"], color=BAND_IQR, lw=0, label="Middle half of years"
        )
        ax.plot(q.index, q["med"], color=MEDIAN, lw=1.2, label="Median")
        for season, lw, col, lab in (
            (prev, 0.9, INK_2, f"{prev}/{str(prev + 1)[2:]}"),
            (cur_season, 2.0, CURRENT, f"{cur_season}/{str(cur_season + 1)[2:]}"),
        ):
            s = d[(d["region"] == region) & (d["season"] == season)].sort_values("doy")
            ax.plot(s["doy"], s["fsc"] * 100, color=col, lw=lw, label=lab)
        ax.set_title(
            f"{REGION_LABEL[region]}, at or above 1800 m", loc="left", color=INK, fontsize=10
        )
        ax.set_xlim(0, 272)
        ax.set_ylim(0, 100)
        ax.set_xticks([t for t, _ in SEASON_TICKS], [lab for _, lab in SEASON_TICKS])
        _style(ax)
    axes[0, 0].set_ylabel("Snow-covered share of the band, %", color=INK_2)
    axes[1, 0].set_ylabel("Snow-covered share of the band, %", color=INK_2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.01, 0.955),
        ncol=5,
        frameon=False,
        fontsize=8,
        labelcolor=INK_2,
    )
    last = d[d["season"] == cur_season]["date"].max()
    fig.suptitle(
        f"Alpine snow cover from MODIS, snow season 1 October to 30 June (latest day "
        f"{last:%d %b %Y})",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11.5,
    )
    fig.text(
        0.01,
        0.01,
        "Daily fractional snow cover, Terra then Aqua, cloud gaps filled from "
        "the previous 8 days; days under 70% valid left blank. " + SNOW_CREDIT,
        color=INK_2,
        fontsize=5.5,
        wrap=True,
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.92))
    return _save(fig, out_dir, "snow_tracker")


def forecast_vs_actual(res: dict, out_dir: Path = config.FIGURES) -> list[Path]:
    wf = pd.DataFrame(res["primary"]["wf_rows"])
    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.plot(
        wf["year"],
        wf["c0"],
        color=HOLLOW,
        lw=1.2,
        ls="--",
        marker="o",
        ms=4,
        label="C0, 10-year average",
    )
    ax.plot(
        wf["year"],
        wf["c1"],
        color=C1_COLOR,
        lw=1.5,
        marker="s",
        ms=4,
        label="C1, starting storage only",
    )
    ax.plot(
        wf["year"],
        wf["full"],
        color=FULL_COLOR,
        lw=2,
        marker="o",
        ms=5,
        label="Snow model (MODIS, 1 May)",
    )
    ax.plot(wf["year"], wf["y"], color=INK, lw=0, marker="D", ms=6, label="Actual")
    for yr in (2022, 2026):
        r = wf[wf["year"] == yr]
        if len(r):
            ax.annotate(
                str(yr),
                (yr, float(r["y"].iloc[0])),
                xytext=(-10, -4),
                textcoords="offset points",
                ha="right",
                color=INK,
                fontsize=9,
            )
    p = res["primary"]["walk_forward"]
    ax.text(
        0.0,
        1.01,
        f"Skill vs C1 {p['skill_vs_c1']:+.2f}, vs C0 {p['skill_vs_c0']:+.2f}; "
        f"Clark-West p {p['clark_west_vs_c1']['p_one_sided']:.2f} "
        f"(Holm {res['holm']['adjusted_p']['H3a']:.2f}). Verdict: {res['verdict']}.",
        transform=ax.transAxes,
        va="bottom",
        color=INK_2,
        fontsize=8.5,
    )
    ax.set_ylabel("Fill on the last Sunday of September, % of capacity", color=INK_2)
    ax.set_title(
        "End-of-season fill, Wallis + Graubuenden + Tessin: walk-forward forecasts made on 1 May",
        loc="left",
        color=INK,
        fontsize=11,
        pad=20,
    )
    ax.set_xticks(wf["year"], [str(y) for y in wf["year"]], fontsize=8)
    ax.set_ylim(72, 92)
    ax.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=INK_2, ncol=2)
    _style(ax)
    fig.text(0.01, 0.01, SNOW_CREDIT, color=INK_2, fontsize=5.5, wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, out_dir, "h3a_forecast_vs_actual")


def snow_vs_refill(f: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    d = f[(f["issue"] == "may1") & (f["band_m"] == 1800) & f["region"].isin(snow.CANTONS)]
    d = d.dropna(subset=["modis_fsc", "refill_gwh"]).copy()
    # Descriptive only: each region's FSC minus its own 2001-2026 mean.
    d["anom"] = (d["modis_fsc"] - d.groupby("region")["modis_fsc"].transform("mean")) * 100
    fig, ax = plt.subplots(figsize=(7.4, 5.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    for region, (col, mk) in REGION_STYLE.items():
        g = d[d["region"] == region]
        ax.plot(g["anom"], g["refill_gwh"], mk, color=col, ms=6, mec=SURFACE, mew=1, label=region)
        for yr in (2022, 2026):
            r = g[g["year"] == yr]
            if len(r):
                ax.annotate(
                    str(yr),
                    (float(r["anom"].iloc[0]), float(r["refill_gwh"].iloc[0])),
                    xytext=(5, 3),
                    textcoords="offset points",
                    color=INK_2,
                    fontsize=7.5,
                )
    ax.axvline(0, color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel(
        "1 May snow cover at or above 1800 m, points from the region's 2001-2026 mean", color=INK_2
    )
    ax.set_ylabel("Refill, spring minimum to end of September, GWh", color=INK_2)
    ax.set_title(
        "Snow on 1 May against refill, one dot per year and region",
        loc="left",
        color=INK,
        fontsize=11,
    )
    ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK_2)
    _style(ax)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    fig.text(0.01, 0.01, SNOW_CREDIT, color=INK_2, fontsize=5.5, wrap=True)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, out_dir, "h3_snow_vs_refill")


def h3b_scatter(res: dict, q4: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    h = res["h3b"]
    x = pd.Series({int(k): v for k, v in h["x_by_year"].items()})
    y = q4.set_index("year")["q4_spread_eur_mwh"].reindex(x.index)
    fig, ax = plt.subplots(figsize=(7.4, 5.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    b = h["slope_per10"] / 10
    a = float(y.mean() - b * x.mean())
    xs = np.linspace(x.min() - 1, x.max() + 1, 2)
    ax.plot(xs, a + b * xs, color=MEDIAN, lw=1.5, zorder=1)
    ax.plot(x, y, "o", color=FULL_COLOR, ms=7, mec=SURFACE, mew=1.2, zorder=2)
    for yr in x.index:
        ax.annotate(
            str(yr),
            (x[yr], y[yr]),
            xytext=(5, 3),
            textcoords="offset points",
            color=INK_2,
            fontsize=7.5,
        )
    ax.axhline(0, color=GRID, lw=0.8, zorder=0)
    ax.axvline(0, color=GRID, lw=0.8, zorder=0)
    lo, hi = h["ci95_per10"]
    ax.text(
        0.0,
        1.01,
        f"Slope {h['slope_per10']:+.1f} EUR/MWh per 10 points (95% {lo:+.1f} to {hi:+.1f}, "
        f"HC3)\nClark-West p {h['clark_west_vs_mean']['p_one_sided']:.2f}, "
        f"smallest detectable effect {h['mde_per10']:.1f}, n = {h['n']}",
        transform=ax.transAxes,
        va="bottom",
        color=INK_2,
        fontsize=8.5,
    )
    ax.set_xlabel(
        "1 May forecast of end-of-September fill minus its 10-year norm, points", color=INK_2
    )
    ax.set_ylabel("Mean CH minus DE-LU spread, October to December, EUR/MWh", color=INK_2)
    ax.set_title(
        "H3b: forecast fill deviation against the autumn Swiss premium",
        loc="left",
        color=INK,
        fontsize=11,
        pad=32,
    )
    _style(ax)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    fig.text(
        0.01,
        0.01,
        "Spread: yearly means of ENTSO-E Transparency Platform day-ahead prices. " + SNOW_CREDIT,
        color=INK_2,
        fontsize=5.5,
        wrap=True,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, out_dir, "h3b_scatter")


def all_figures(out_dir: Path = config.FIGURES) -> list[Path]:
    from alpinehydro import evaluate_snow

    modis = snow.read_csv(features_snow.MODIS_CSV)
    f = features_snow.load()
    paths = snow_tracker(modis, out_dir) + snow_vs_refill(f, out_dir)
    if evaluate_snow.OUT.exists():
        res = json.loads(evaluate_snow.OUT.read_text(encoding="utf-8"))
        paths += forecast_vs_actual(res, out_dir)
        paths += h3b_scatter(res, features_snow.load_q4(), out_dir)
    return paths
