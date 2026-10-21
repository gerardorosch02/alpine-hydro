"""Figures built from committed SFOE data only (no keys, no prices)."""

from __future__ import annotations

import io
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


def hero_chart(
    storage: pd.DataFrame, wallis: pd.DataFrame | None = None, out_dir: Path = config.FIGURES
) -> list[Path]:
    """National storage band and current year; with `wallis`, a second panel (version 2)
    with SFOE Wallis per year and the satellite Wallis series of the current year."""
    cfg = config.pipeline()["hero"]
    band, current, latest, cy = hero_table(storage)
    first, last = cfg["band_first_hydro_year"], cfg["band_last_hydro_year"]

    if wallis is None:
        fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    else:
        fig, (ax, axw) = plt.subplots(
            2, 1, figsize=(10, 9.4), dpi=150, sharex=True, height_ratios=(1.25, 1)
        )
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
    credit = "Source: Swiss Federal Office of Energy SFOE. Weekly totals, Sunday 24:00."
    if wallis is not None:
        _hero_wallis(axw, storage, wallis, cy)
        credit += (
            "\nSatellite: contains modified Copernicus Sentinel data; Landsat courtesy of the"
            " U.S. Geological Survey; Source: Federal Office of Topography swisstopo."
        )
    fig.text(0.01, 0.01, credit + " Chart: alpine-hydro.", color=INK_2, fontsize=8)
    fig.tight_layout(rect=(0, 0.05 if wallis is not None else 0.03, 1, 1))

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / "hero_storage.png", out_dir / "hero_storage.svg"]
    for p in paths:
        # Save through a byte buffer so the SVG has LF line endings on Windows too.
        buf = io.BytesIO()
        fmt = p.suffix[1:]
        fig.savefig(
            buf, format=fmt, facecolor=SURFACE, metadata={"Date": None} if fmt == "svg" else None
        )
        p.write_bytes(buf.getvalue())
    plt.close(fig)
    return paths


def _hero_wallis(ax, storage: pd.DataFrame, wallis: pd.DataFrame, cy: int) -> None:
    """SFOE Wallis fill per hydrological year from 2017, the current year highlighted, and
    the satellite Wallis series (walk-forward calibrated) of the current year as dots."""
    ax.set_facecolor(SURFACE)
    w = storage[storage["region"] == "Wallis"].copy()
    iso = w["valid_time"].dt.isocalendar()
    w["hy"] = hydro_year(iso["year"].astype(int), iso["week"].astype(int))
    w["pos"] = hydro_position(iso["week"].astype(int))
    w = w[(w["hy"] >= 2017) & (iso["week"] <= 52)]
    for y, g in w.groupby("hy"):
        if y == cy:
            continue
        ax.plot(g["pos"], g["fill"] * 100, color=BAND_RANGE, lw=1.0)
    cur = w[w["hy"] == cy].sort_values("pos")
    ax.plot(
        cur["pos"],
        cur["fill"] * 100,
        color=CURRENT,
        lw=2.2,
        label=f"SFOE Wallis {cy}/{str(cy + 1)[2:]}",
    )
    s = wallis.copy()
    iso = s["valid_time"].dt.isocalendar()
    s["hy"] = hydro_year(iso["year"].astype(int), iso["week"].astype(int))
    s["pos"] = hydro_position(iso["week"].astype(int))
    s = s[(s["hy"] == cy) & s["sat_fill_pp"].notna()]
    ok, other = s[s["ok"]], s[~s["ok"]]
    ax.plot(
        other["pos"],
        other["sat_fill_pp"],
        "o",
        mfc="none",
        mec=MEDIAN,
        ms=5,
        mew=1,
        label="Satellite, week not ok",
    )
    ax.plot(
        ok["pos"],
        ok["sat_fill_pp"],
        "o",
        color=MEDIAN,
        ms=5,
        label="Satellite (Dix + Emosson + Mauvoisin, calibrated)",
    )
    ax.plot([], [], color=BAND_RANGE, lw=1.0, label="SFOE Wallis, 2017/18 onwards")
    ax.set_ylim(0, 100)
    ax.set_ylabel("Valais (Wallis) storage, % of capacity", color=INK_2)
    ax.set_title(
        "Valais: SFOE against three reservoirs seen from space (June to November)",
        loc="left",
        color=INK,
        fontsize=11,
    )
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.56, 1.0),
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_2,
    )
    _style(ax)


# ---------------------------------------------------------------- Part A: satellite

HOLLOW = "#9a9993"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0)


def _save(fig, out_dir: Path, stem: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{stem}.png"]
    for p in paths:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=SURFACE)
        p.write_bytes(buf.getvalue())
    plt.close(fig)
    return paths


def reservoir_chart(
    slug: str, scenes: pd.DataFrame, storage: pd.DataFrame, out_dir: Path = config.FIGURES
) -> list[Path]:
    """Level per scene (top) and satellite fill against the SFOE region fill (bottom)."""
    from alpinehydro import hypsometry

    r = hypsometry.reservoir(slug)
    info = hypsometry.curve_info(slug)
    sc = scenes[(scenes["reservoir"] == slug) & scenes["level_m"].notna()].copy()
    sc["time_utc"] = pd.to_datetime(sc["time_utc"], utc=True).dt.tz_localize(None)
    ok = sc[sc["flag"] == "ok"]
    is_ice = sc["flag"].str.contains("ice_likely")
    ice = sc[is_ice]
    other = sc[(sc["flag"] != "ok") & ~is_ice]
    reg = storage[storage["region"] == r["sfoe_region"]]
    reg = reg[reg["valid_time"] >= sc["time_utc"].min()]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.5), dpi=130, sharex=True)
    fig.patch.set_facecolor(SURFACE)
    ax1.plot(
        other["time_utc"],
        other["level_m"],
        "o",
        mfc="none",
        mec=HOLLOW,
        ms=3.5,
        mew=0.8,
        label=f"Other scenes, flagged ({len(other)})",
    )
    ax1.plot(
        ice["time_utc"],
        ice["level_m"],
        "x",
        color=HOLLOW,
        ms=3.5,
        mew=0.8,
        label=f"Lake ice likely ({len(ice)})",
    )
    ax1.plot(
        ok["time_utc"], ok["level_m"], "o", color=MEDIAN, ms=3.5, label=f"ok scenes ({len(ok)})"
    )
    ax1.axhline(r["full_level_m"], color=INK_2, lw=0.9, ls="--")
    ax1.text(
        sc["time_utc"].min(),
        r["full_level_m"],
        " full supply",
        va="bottom",
        color=INK_2,
        fontsize=8,
    )
    ax1.axhline(info["floor_m"], color=CURRENT, lw=0.9, ls=":")
    ax1.text(
        sc["time_utc"].min(),
        info["floor_m"],
        " swissALTI3D floor (2 m data above)",
        va="top",
        ha="left",
        color=CURRENT,
        fontsize=8,
        bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1},
        zorder=5,
    )
    if info.get("global_floor_m"):
        ax1.axhline(info["global_floor_m"], color=CURRENT, lw=0.9, ls="-.")
        ax1.text(
            sc["time_utc"].min(),
            info["global_floor_m"],
            f" {info['global_dem']} floor (30 m data above, fitted below)",
            va="bottom",
            color=CURRENT,
            fontsize=8,
        )
    ax1.set_ylabel("Water level, m a.s.l.", color=INK_2)
    ax1.legend(
        loc="lower right",
        bbox_to_anchor=(1, 1),
        ncol=3,
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_2,
    )
    _style(ax1)

    ax2.plot(
        reg["valid_time"],
        reg["fill"] * 100,
        color=INK_2,
        lw=1.2,
        label=f"SFOE {r['sfoe_region']} fill (region)",
    )
    ax2.plot(other["time_utc"], other["fill"] * 100, "o", mfc="none", mec=HOLLOW, ms=3.5, mew=0.8)
    ax2.plot(ice["time_utc"], ice["fill"] * 100, "x", color=HOLLOW, ms=3.5, mew=0.8)
    ax2.plot(
        ok["time_utc"],
        ok["fill"] * 100,
        "o",
        color=MEDIAN,
        ms=3.5,
        label=f"{r['name']} fill from satellite",
    )
    ax2.set_ylabel("Fill, % of usable volume", color=INK_2)
    ax2.legend(
        loc="lower right",
        bbox_to_anchor=(1, 1),
        ncol=3,
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_2,
    )
    _style(ax2)

    quality = f" (fill {r['fill_quality']})" if r.get("fill_quality") else ""
    fig.suptitle(
        f"{r['name']}: water level and fill from Sentinel-2 and Landsat{quality}",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    fig.text(
        0.01,
        0.01,
        "Contains modified Copernicus Sentinel data. Landsat courtesy of the U.S. Geological "
        "Survey. Source: Federal Office of Topography swisstopo; Swiss Federal Office of "
        "Energy SFOE.\nContains modified Copernicus Climate Change Service information "
        "(ERA5-Land, ice flag only).",
        color=INK_2,
        fontsize=7,
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.97))
    return _save(fig, out_dir, f"reservoir_{slug}")


SAT_CREDIT = (
    "Contains modified Copernicus Sentinel data. Landsat courtesy of the U.S. Geological "
    "Survey. Source: Federal Office of Topography swisstopo; Swiss Federal Office of Energy SFOE."
)
MONTH_COLORS = {
    6: "#86b6ef",
    7: "#3d85d8",
    8: "#184f95",
    9: "#eb6834",
    10: "#b8461b",
    11: "#52514e",
}
MONTH_NAMES = {6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov"}


def validation_scatter(wallis: pd.DataFrame, m: dict, out_dir: Path = config.FIGURES) -> list[Path]:
    """Satellite against SFOE Wallis anomalies on scored weeks, coloured by month."""
    s = wallis.dropna(subset=["sat_anom_pp", "sfoe_anom_pp"])
    fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    lim = float(max(s["sat_anom_pp"].abs().max(), s["sfoe_anom_pp"].abs().max(), 1)) * 1.1
    ax.plot([-lim, lim], [-lim, lim], color=GRID, lw=1, zorder=0)
    ax.axhline(0, color=GRID, lw=0.8, zorder=0)
    ax.axvline(0, color=GRID, lw=0.8, zorder=0)
    for mo, g in s.groupby(s["valid_time"].dt.month):
        ax.plot(
            g["sfoe_anom_pp"],
            g["sat_anom_pp"],
            "o",
            color=MONTH_COLORS.get(mo, INK_2),
            ms=5,
            label=MONTH_NAMES.get(mo, str(mo)),
        )
    verdict = "pass" if m.get("pass") else "fail"
    ax.text(
        0.03,
        0.97,
        f"R² = {m.get('r2', float('nan')):.2f} ({verdict}, mark 0.50)\n"
        f"MAE = {m.get('mae_pp', float('nan')):.1f} pp, "
        f"fill bias = {m.get('fill_bias_pp', float('nan')):+.1f} pp\n"
        f"n = {m.get('n', 0)} weeks, {m.get('years', '')}",
        transform=ax.transAxes,
        va="top",
        color=INK,
        fontsize=9,
    )
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("SFOE Wallis anomaly, pp of capacity", color=INK_2)
    ax.set_ylabel("Satellite Wallis anomaly, pp of capacity", color=INK_2)
    ax.set_title("Valais anomalies, June to November ok weeks", loc="left", color=INK, fontsize=11)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5, labelcolor=INK_2, title_fontsize=8)
    _style(ax)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    fig.text(0.01, 0.01, SAT_CREDIT, color=INK_2, fontsize=5.5, wrap=True)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save(fig, out_dir, "validation_scatter")


COVERAGE_CLASSES = [
    ("ok", "ok", MEDIAN),
    ("level not trusted", "level not trusted (below floor, no match)", BAND_IQR),
    ("ice or snow", "ice or snow", "#c9c7c0"),
    ("cloud", "cloud", "#8f8d86"),
    ("no scene", "no scene within 3 days", SURFACE),
    ("not searched", "month not searched", GRID),
]


def coverage_table(scenes: pd.DataFrame, storage: pd.DataFrame, slugs: list[str]) -> pd.DataFrame:
    """Best scene class per reservoir and SFOE week from 2017 (closest within 3 days)."""
    from alpinehydro import water_mask

    weeks = storage[storage["region"] == "TotalCH"][["valid_time", "datum"]].drop_duplicates()
    weeks = weeks[weeks["valid_time"] >= "2017-04-01"]
    end = weeks["datum"].dt.tz_localize("Europe/Zurich").dt.tz_convert("UTC")
    order = {c[0]: i for i, c in enumerate(COVERAGE_CLASSES)}
    rows = []
    for slug in slugs:
        sc = scenes[scenes["reservoir"] == slug].copy()
        sc["time_utc"] = pd.to_datetime(sc["time_utc"], utc=True)
        f = sc["flag"].fillna("")
        sc["cls"] = "level not trusted"
        sc.loc[f.str.contains("cloud"), "cls"] = "cloud"
        sc.loc[f.str.contains("snow_ice|ice_likely"), "cls"] = "ice or snow"
        sc.loc[f == "ok", "cls"] = "ok"
        sc["rank"] = sc["cls"].map(order)
        mon = set(water_mask.months(slug))
        t = sc["time_utc"].dt.tz_convert(None).to_numpy()
        for vt, we in zip(weeks["valid_time"], end, strict=True):
            if vt.month not in mon:
                cls = "not searched"
            else:
                near = sc[
                    abs(t - we.tz_convert(None).to_datetime64())
                    <= pd.Timedelta(days=3).to_timedelta64()
                ]
                cls = near.sort_values("rank")["cls"].iloc[0] if len(near) else "no scene"
            rows.append({"reservoir": slug, "valid_time": vt, "cls": cls})
    return pd.DataFrame(rows)


def coverage_map(cov: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    """Reservoir by week from 2017, coloured by the best scene class."""
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    from alpinehydro import hypsometry

    slugs = list(dict.fromkeys(cov["reservoir"]))
    code = {c[0]: i for i, c in enumerate(COVERAGE_CLASSES)}
    grid = cov.assign(c=cov["cls"].map(code)).pivot(
        index="reservoir", columns="valid_time", values="c"
    )
    grid = grid.loc[slugs]
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(slugs) + 1.9), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    cmap = ListedColormap([c[2] for c in COVERAGE_CLASSES])
    t = grid.columns
    x = matplotlib.dates.date2num(pd.to_datetime(t))
    ax.pcolormesh(
        list(x) + [x[-1] + 7],
        range(len(slugs) + 1),
        grid.to_numpy(),
        cmap=cmap,
        vmin=-0.5,
        vmax=len(COVERAGE_CLASSES) - 0.5,
        edgecolors="none",
    )
    ax.xaxis_date()
    names = [hypsometry.reservoir(s)["name"] for s in slugs]
    ax.set_yticks([i + 0.5 for i in range(len(slugs))], names)
    ax.invert_yaxis()
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=INK_2, length=0)
    handles = [Patch(facecolor=c[2], edgecolor=GRID, label=c[1]) for c in COVERAGE_CLASSES]
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0, -0.12),
        ncol=3,
        frameon=False,
        fontsize=8,
        labelcolor=INK_2,
    )
    ax.set_title(
        "Which weeks free satellite data can see (closest scene within 3 days of each SFOE week)",
        loc="left",
        color=INK,
        fontsize=11,
    )
    fig.text(0.01, 0.01, SAT_CREDIT, color=INK_2, fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, out_dir, "coverage_map")


def sihlsee_showcase(scenes: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    """Sihlsee level through the year from both methods, with the terrain floor and full level."""
    from alpinehydro import hypsometry

    r = hypsometry.reservoir("sihlsee")
    floor = hypsometry.curve_info("sihlsee")["floor_m"]
    sc = scenes[(scenes["reservoir"] == "sihlsee")].copy()
    sc["time_utc"] = pd.to_datetime(sc["time_utc"], utc=True)
    sc["doy"] = sc["time_utc"].dt.dayofyear
    ok = sc[sc["flag"] == "ok"]
    below = sc[
        sc["flag"].fillna("").str.contains("below_floor")
        & ~sc["flag"].fillna("").str.contains("ice|snow|cloud")
    ]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.plot(
        below["doy"],
        below["level_m"],
        "o",
        mfc="none",
        mec=HOLLOW,
        ms=3.5,
        mew=0.8,
        label=f"Below the floor: level from water area and the fitted curve ({len(below)})",
    )
    ax.plot(
        ok["doy"],
        ok["level_shoreline_m"],
        "^",
        color=BAND_IQR,
        ms=3.5,
        label=f"ok scenes, shoreline method ({len(ok)})",
    )
    ax.plot(
        ok["doy"],
        ok["level_iou_m"],
        "o",
        color=MEDIAN,
        ms=3.5,
        label="ok scenes, mask matching method",
    )
    ax.axhline(r["full_level_m"], color=INK_2, lw=0.9, ls="--")
    ax.text(2, r["full_level_m"], " full supply", va="bottom", color=INK_2, fontsize=8)
    ax.axhline(floor, color=CURRENT, lw=0.9, ls=":")
    ax.text(
        2,
        floor,
        " swissALTI3D floor: 2 m terrain above, fitted curve below",
        va="top",
        color=CURRENT,
        fontsize=8,
    )
    starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    ax.set_xticks(
        starts, ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
    ax.set_xlim(1, 366)
    lo = float(below["level_m"].quantile(0.05)) if len(below) else floor - 5
    ax.set_ylim(min(lo, floor - 3), r["full_level_m"] + 1)
    ax.set_ylabel("Water level, m a.s.l.", color=INK_2)
    ax.set_title(
        "Sihlsee through the year, 2013 to 2026: two ways to read a level from a water mask",
        loc="left",
        color=INK,
        fontsize=11,
    )
    ax.legend(loc="lower left", frameon=False, fontsize=8.5, labelcolor=INK_2)
    _style(ax)
    fig.text(0.01, 0.01, SAT_CREDIT, color=INK_2, fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, out_dir, "sihlsee_showcase")


def example_scene(slug: str, scene: pd.Series, out_dir: Path = config.FIGURES) -> list[Path]:
    """Water mask outline over a true-colour Sentinel-2 crop, with the matched terrain contour.

    Needs Earth Engine and the cached masks, so `demo` keeps the committed PNG instead.
    """
    import numpy as np

    from alpinehydro import hypsometry, water_mask

    date = str(scene["time_utc"])[:10]
    g = hypsometry.load_grid(slug)
    hyb = np.load(hypsometry.hybrid_path(slug))
    lake_max = hyb["join"] <= float(hypsometry.reservoir(slug)["full_level_m"])
    m = water_mask.classify(
        water_mask.load_arrays(water_mask.mask_path(slug, "s2", date)), g.window, lake_max
    )
    rgb = water_mask.pull_rgb(slug, date).astype(float) / 10000
    win = g.window[..., None].repeat(3, axis=2)
    lo, hi = np.percentile(rgb[win], [2, 98])
    img = np.clip((rgb - lo) / (hi - lo), 0, 1) ** 0.9
    ys, xs = np.where(g.window)
    sl = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    h, w = img[sl].shape[:2]
    fig, ax = plt.subplots(figsize=(4.2, 4.2 * h / w + 0.6), dpi=80)
    fig.patch.set_facecolor(SURFACE)
    ax.imshow(img[sl], interpolation="nearest")
    ax.contour((m["water"] & lake_max)[sl].astype(float), [0.5], colors="#3df2ff", linewidths=0.9)
    ax.contour(
        (hyb["join"] <= float(scene["level_m"]))[sl].astype(float),
        [0.5],
        colors=CURRENT,
        linewidths=0.9,
        linestyles="--",
    )
    ax.set_axis_off()
    name = hypsometry.reservoir(slug)["name"]
    ax.set_title(
        f"{name}, {date}: water mask (cyan) and terrain\nat the matched level "
        f"{float(scene['level_m']):.1f} m (orange, dashed)",
        loc="left",
        color=INK,
        fontsize=8.5,
    )
    fig.text(
        0.01,
        0.01,
        f"Contains modified Copernicus Sentinel data {date[:4]}.\n"
        "Source: Federal Office of Topography swisstopo.",
        color=INK_2,
        fontsize=6,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    paths = _save(fig, out_dir, f"example_scene_{slug}")
    # Keep the committed PNG small: 256 colours are plenty at this size.
    from PIL import Image

    for p in paths:
        Image.open(p).convert("RGB").quantize(256).save(p, optimize=True)
    return paths


# ---------------------------------------------------------------- H1 price test

PRICE_CREDIT = (
    "Prices: ENTSO-E Transparency Platform (day-ahead, CH and DE-LU; not redistributed). "
    "Storage: Swiss Federal Office of Energy SFOE."
)


def h1_scatter(f: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    """Deviation against the next-28-day CH minus DE-LU spread, one dot per origin."""

    d = f[(f["winter"] >= 2015) & (f["y_days"] == 28)]
    fig, ax = plt.subplots(figsize=(9, 5.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    winters = sorted(d["winter"].unique())
    cmap = plt.get_cmap("Blues")
    for i, w in enumerate(winters):
        g = d[d["winter"] == w]
        crisis = w in (2021, 2022)
        ax.plot(
            g["dev_10y_pp"],
            g["y"],
            "D" if crisis else "o",
            color=CURRENT
            if w == 2021
            else ("#b8461b" if w == 2022 else cmap(0.35 + 0.6 * i / len(winters))),
            ms=5 if crisis else 4,
            label=f"{w}/{str(w + 1)[2:]}" + (" (crisis)" if crisis else ""),
        )
    ax.axhline(0, color=GRID, lw=0.8)
    ax.axvline(0, color=GRID, lw=0.8)
    ax.set_xlabel("Storage deviation from the 10-year norm at the origin, points", color=INK_2)
    ax.set_ylabel("Mean CH minus DE-LU spread, next 28 days, EUR/MWh", color=INK_2)
    ax.set_title(
        "H1 data: one dot per weekly origin, November to April, 2015/16 to 2025/26",
        loc="left",
        color=INK,
        fontsize=11,
    )
    ax.legend(loc="upper right", frameon=False, fontsize=7.5, labelcolor=INK_2, ncol=2)
    _style(ax)
    ax.xaxis.grid(True, color=GRID, lw=0.8)

    fig.text(0.01, 0.01, PRICE_CREDIT, color=INK_2, fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return _save(fig, out_dir, "h1_scatter")


def h1_oos(o: pd.DataFrame, out_dir: Path = config.FIGURES) -> list[Path]:
    """Full model and B3 forecasts against the realised spread, by test winter."""
    winters = sorted(o["winter"].unique())
    fig, axes = plt.subplots(1, len(winters), figsize=(13, 4.2), dpi=150, sharey=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, w in zip(axes, winters, strict=True):
        g = o[o["winter"] == w].sort_values("origin_day")
        ax.plot(g["origin_day"], g["y_raw"], color=INK, lw=1.4, label="Realised")
        ax.plot(g["origin_day"], g["y"], color=INK_2, lw=0.8, ls=":", label="Realised, clipped")
        ax.plot(g["origin_day"], g["b3"], color=BAND_IQR, lw=1.3, label="B3, controls only")
        ax.plot(g["origin_day"], g["full"], color=CURRENT, lw=1.3, label="Full model")
        ax.set_title(f"{w}/{str(w + 1)[2:]}", loc="left", color=INK, fontsize=10)
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
        _style(ax)
    axes[0].set_ylabel("28-day CH minus DE-LU spread, EUR/MWh", color=INK_2)
    axes[0].legend(loc="upper left", frameon=False, fontsize=7, labelcolor=INK_2)
    fig.suptitle(
        "H1 out of sample: forecasts made at each origin against what happened",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.text(0.01, 0.01, PRICE_CREDIT, color=INK_2, fontsize=7)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return _save(fig, out_dir, "h1_out_of_sample")


def h1_scorecard(
    rows: list[tuple[str, str, str, str]], out_dir: Path = config.FIGURES
) -> list[Path]:
    """Pre-registration scorecard: test, what was pre-registered, result, pass or fail."""
    fig, ax = plt.subplots(figsize=(12, 0.3 * len(rows) + 0.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_axis_off()
    table = ax.table(
        cellText=[list(r) for r in rows],
        colLabels=["Test", "Pre-registered", "Result", "Outcome"],
        colWidths=[0.22, 0.33, 0.33, 0.12],
        loc="upper left",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1, 1.5)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(SURFACE if r else "#f1f0ec")
        if r and c == 3:
            txt = cell.get_text().get_text()
            cell.get_text().set_color(CURRENT if txt in ("fail", "holds") else MEDIAN)
    ax.set_title("H1 pre-registration scorecard", loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    return _save(fig, out_dir, "h1_scorecard")
