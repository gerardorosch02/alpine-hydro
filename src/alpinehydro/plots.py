"""Figures built from committed SFOE data only (no keys, no prices)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = (
    "alpine-hydro"  # stable SVG ids, so rebuilds are byte-identical
)
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from alpinehydro import config  # noqa: E402
from alpinehydro.norms import add_norms  # noqa: E402

# Reference palette: one blue ramp for the history bands, orange for the current year.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e0"
BAND_RANGE = "#cde2fb"
BAND_IQR = "#86b6ef"
MEDIAN = "#184f95"
CURRENT = "#eb6834"

MONTH_TICKS = [
    (40, "Oct"),
    (44, "Nov"),
    (48, "Dec"),
    (1, "Jan"),
    (5, "Feb"),
    (9, "Mar"),
    (14, "Apr"),
    (18, "May"),
    (22, "Jun"),
    (27, "Jul"),
    (31, "Aug"),
    (36, "Sep"),
]


def hydro_position(week_key: pd.Series) -> pd.Series:
    """Position on a hydrological-year axis: ISO week 40 is 0, week 39 is 51."""
    return (week_key - 40) % 52


def hydro_year(iso_year: pd.Series, iso_week: pd.Series) -> pd.Series:
    """Hydrological year label: the calendar year in which it starts (week 40)."""
    return iso_year.where(iso_week >= 40, iso_year - 1)


def hero_table(storage: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, int]:
    """Return (band statistics, current-year line, latest row, current hydro year)."""
    cfg = config.pipeline()["hero"]
    total = storage[storage["region"] == "TotalCH"]
    d = add_norms(total, windows=(10,))
    d["hydro_year"] = hydro_year(d["iso_year"], d["iso_week"])
    d["pos"] = hydro_position(d["week_key"])
    d["fill_pct"] = d["fill"] * 100

    hist = d[
        d["hydro_year"].between(cfg["band_first_hydro_year"], cfg["band_last_hydro_year"])
        & (d["iso_week"] <= 52)
    ]
    band = hist.groupby("pos")["fill_pct"].agg(
        lo="min",
        q25=lambda s: s.quantile(0.25),
        median="median",
        q75=lambda s: s.quantile(0.75),
        hi="max",
        n="count",
    )
    current_year = int(d["hydro_year"].max())
    current = (
        d[d["hydro_year"] == current_year]
        .sort_values("valid_time")
        .drop_duplicates("pos", keep="last")
    )
    latest = d.sort_values("valid_time").iloc[-1]
    return band, current, latest, current_year


def hero_chart(storage: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    cfg = config.pipeline()["hero"]
    band, current, latest, cy = hero_table(storage)
    first, last = cfg["band_first_hydro_year"], cfg["band_last_hydro_year"]

    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = band.index
    ax.fill_between(
        x,
        band["lo"],
        band["hi"],
        color=BAND_RANGE,
        lw=0,
        label=f"Range {first}/{str(first + 1)[2:]} to {last}/{str(last + 1)[2:]}",
    )
    ax.fill_between(x, band["q25"], band["q75"], color=BAND_IQR, lw=0, label="Interquartile range")
    ax.plot(x, band["median"], color=MEDIAN, lw=1.6, ls=(0, (5, 3)), label="Median")
    ax.plot(
        current["pos"],
        current["fill_pct"],
        color=CURRENT,
        lw=2.2,
        solid_capstyle="round",
        label=f"{cy}/{str(cy + 1)[2:]}",
    )
    ax.plot(
        [current["pos"].iloc[-1]],
        [current["fill_pct"].iloc[-1]],
        "o",
        color=CURRENT,
        ms=6,
        mec=SURFACE,
        mew=1.5,
    )

    ticks, labels = zip(*MONTH_TICKS, strict=True)
    ax.set_xticks([(t - 40) % 52 for t in ticks], labels)
    ax.set_xlim(0, 51)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Swiss reservoir storage, % of capacity", color=INK_2)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0)

    dev = latest["dev_10y_pp"]
    when = latest["valid_time"].strftime("%d %b %Y")
    ax.set_title(
        "Swiss hydro storage across the hydrological year (October to September)",
        loc="left",
        color=INK,
        fontsize=12.5,
        pad=26,
    )
    ax.text(
        0,
        1.035,
        f"Week ending {when}: {latest['fill_pct']:.1f}% full, "
        f"{dev:+.1f} points against the 10-year norm (past-only median)",
        transform=ax.transAxes,
        color=INK_2,
        fontsize=10,
    )
    ax.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=INK_2)
    fig.text(
        0.01,
        0.01,
        "Source: Swiss Federal Office of Energy SFOE. Weekly totals, "
        "Sunday 24:00. Chart: alpine-hydro.",
        color=INK_2,
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / "hero_storage.png", out_dir / "hero_storage.svg"]
    for p in paths:
        fig.savefig(p, facecolor=SURFACE, metadata={"Date": None} if p.suffix == ".svg" else None)
    plt.close(fig)
    return paths
