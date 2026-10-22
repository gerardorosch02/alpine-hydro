"""GitHub social preview (1280 x 640) from the hero chart.

Run from the repo root: uv run python scripts/make_social_preview.py
"""

import io

import matplotlib.pyplot as plt

from alpinehydro import config, plots
from alpinehydro.fetch import sfoe_pdf
from alpinehydro.plots import (
    BAND_IQR,
    BAND_RANGE,
    CURRENT,
    GRID,
    INK,
    INK_2,
    MEDIAN,
    MONTH_TICKS,
    PREVIOUS,
    SURFACE,
)

storage = sfoe_pdf.load_merged()
cfg = config.pipeline()["hero"]
band, current, latest, cy = plots.hero_table(storage)
first, last = cfg["band_first_hydro_year"], cfg["band_last_hydro_year"]

fig, ax = plt.subplots(figsize=(12.8, 6.4), dpi=100)
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
ax.plot(x, band["median"], color=MEDIAN, lw=2.4, ls=(0, (5, 3)), label="Median")
if len(current) < 13:
    prev = plots._hydro_year_line(storage, cy - 1)
    ax.plot(
        prev["pos"],
        prev["fill_pct"],
        color=PREVIOUS,
        lw=2.8,
        solid_capstyle="round",
        label=f"{cy - 1}/{str(cy)[2:]}",
    )
ax.plot(
    current["pos"],
    current["fill_pct"],
    color=CURRENT,
    lw=3.6,
    solid_capstyle="round",
    label=f"{cy}/{str(cy + 1)[2:]}",
)
ax.plot(
    current["pos"].iloc[-1:],
    current["fill_pct"].iloc[-1:],
    "o",
    color=CURRENT,
    ms=11,
    mec=SURFACE,
    mew=2,
)

ticks, labels = zip(*MONTH_TICKS, strict=True)
ax.set_xticks([(t - 40) % 52 for t in ticks], labels)
ax.set_xlim(0, 51)
ax.set_ylim(0, 100)
ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
ax.yaxis.grid(True, color=GRID, lw=1)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(GRID)
ax.tick_params(colors=INK_2, length=0, labelsize=15)

when = latest["valid_time"].strftime("%d %b %Y")
fig.text(
    0.035,
    0.915,
    "Swiss hydro storage, % of capacity",
    color=INK,
    fontsize=32,
    fontweight="bold",
    va="baseline",
)
fig.text(
    0.035,
    0.85,
    f"Week ending {when}: {latest['fill_pct']:.1f}% full, "
    f"{latest['dev_10y_pp']:+.1f} points against the 10-year norm",
    color=INK_2,
    fontsize=18,
    va="baseline",
)
fig.text(0.97, 0.955, "alpine-hydro", color=INK_2, fontsize=12, ha="right", va="baseline")
ax.legend(loc="lower left", frameon=False, fontsize=13, labelcolor=INK_2)
fig.text(0.035, 0.025, "Source: Swiss Federal Office of Energy SFOE", color=INK_2, fontsize=10)
fig.subplots_adjust(left=0.07, right=0.97, top=0.79, bottom=0.12)

out = config.FIGURES / "social_preview.png"
buf = io.BytesIO()
fig.savefig(buf, format="png", facecolor=SURFACE, dpi=100)
out.write_bytes(buf.getvalue())
print(out, len(buf.getvalue()))
