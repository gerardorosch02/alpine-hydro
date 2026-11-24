"""Live check, winter 2026/27 (pre-registration section 9): one forecast per new origin.

- Model: the full H1 model (and B3, for comparison) trained on every origin of the winters
  2015/16 to 2025/26, with cut-offs from that training set.
- Origin: the latest SFOE week in the merged table (sfoe_storage_merged.csv: CSV where it
  has the week, weekly PDF for newer weeks), if its valid Sunday falls in November to April
  and it has no forecast yet. known_time is the time the week was first seen: the PDF log
  for a PDF week, the CSV release log for a CSV week. The target window starts after it.
- Output: data/processed/live_forecasts.csv (committed: forecasts and inputs only). The
  realised mean spread, one derived number per window, is added later in realised_spread.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from alpinehydro import config, features, models

OUT = config.PROCESSED / "live_forecasts.csv"
TZ = "Europe/Zurich"
COLUMNS = [
    "valid_sunday",
    "known_time",
    "known_time_source",
    "origin_day",
    "target_start",
    "target_end",
    "dev_10y_pp",
    *models.PRIMARY_CONTROLS,
    "forecast_full",
    "forecast_b3",
    "made_at_utc",
    "model",
    "realised_spread",
    "note",
]
# Pre-registration section 9: origins from November 2026 to April 2027.
LIVE_FIRST = pd.Timestamp("2026-11-01")
LIVE_LAST = pd.Timestamp("2027-04-30")
MERGE_LOG = config.PROCESSED / "sfoe_merge_log.csv"


def train() -> dict:
    """Full model and B3 on all winters to 2025/26, training cut-offs."""
    d = models.prepare(features.load(), models.PRIMARY_CONTROLS)
    d = d[d["winter"] <= 2025]
    cut = models.cutoffs(d)
    tr = models.clip(d, cut)
    months = models._months_in(tr)
    pc = models.PRIMARY_CONTROLS
    return {
        "full": models.ols(models.design(tr, pc, True, months), tr["y"].to_numpy()),
        "b3": models.ols(models.design(tr, pc, False, months), tr["y"].to_numpy()),
        "cut": cut,
        "months": months,
        "label": f"full H1 model, OLS on {len(tr)} origins, winters 2015/16 to 2025/26",
    }


def _week(row: pd.Series, storage: pd.DataFrame) -> dict:
    """One TotalCH week of the merged table, its source and its first-seen time."""
    last = row["valid_time"]
    if row["source"] == "pdf":
        seen = row["known_time"].tz_convert("UTC")
        src = "SFOE weekly PDF, first seen in sfoe_pdf_log.csv"
    else:
        rel = pd.read_csv(config.PROCESSED / "sfoe_release_log.csv", parse_dates=["valid_sunday"])
        hit = rel.loc[rel["valid_sunday"] == last, "first_seen_utc"]
        seen = pd.Timestamp(hit.iloc[0]) if len(hit) else None
        src = "SFOE CSV, first seen in sfoe_release_log.csv"
    return {"valid_sunday": last, "first_seen_utc": seen, "source": src, "storage": storage}


def _total(storage: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    from alpinehydro.fetch import sfoe_pdf

    s = sfoe_pdf.load_merged() if storage is None else storage
    return s, s[s["region"] == "TotalCH"].sort_values("valid_time")


def latest_week() -> dict:
    """Latest week of the merged table, its source and its first-seen time."""
    s, total = _total()
    return _week(total.iloc[-1], s)


def pending_origins(storage: pd.DataFrame | None = None, done: pd.DataFrame | None = None) -> list:
    """Every live origin without a forecast, oldest first: SFOE weeks of the merged table
    whose valid Sunday lies in the live winter (LIVE_FIRST to LIVE_LAST, November to April).
    A week that an earlier run missed is still listed, so it is forecast late, not lost."""
    s, total = _total(storage)
    have = set((load() if done is None else done)["valid_sunday"].astype(str))
    vt = total["valid_time"]
    live = total[(vt >= LIVE_FIRST) & (vt <= LIVE_LAST) & vt.dt.month.isin(features.SEASON_MONTHS)]
    return [_week(r, s) for _, r in live.iterrows() if str(r["valid_time"].date()) not in have]


def next_possible(after: pd.Timestamp) -> pd.Timestamp:
    """First Sunday in November to April after the given Sunday."""
    d = after + pd.Timedelta(days=7)
    while d.month not in features.SEASON_MONTHS:
        d += pd.Timedelta(days=7)
    return d


def storage_as_known(
    storage: pd.DataFrame,
    valid_sunday: pd.Timestamp,
    known_time: pd.Timestamp,
    merge_log: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """TotalCH rows up to the origin week, with that week's value as it stood at known_time.

    SFOE can revise a week in a later PDF, and the CSV later replaces the PDF value. Each
    such replacement is in sfoe_merge_log.csv with the old value. If the week was replaced
    after known_time, the value before the earliest of those replacements is put back, so
    a forecast made late sees what a forecast made on time would have seen.
    """
    d = storage[(storage["region"] == "TotalCH") & (storage["valid_time"] <= valid_sunday)].copy()
    if merge_log is None:
        merge_log = pd.read_csv(MERGE_LOG) if MERGE_LOG.exists() else pd.DataFrame()
    if merge_log.empty:
        return d
    when = pd.to_datetime(merge_log["logged_utc"], utc=True)
    hit = merge_log[
        (merge_log["region"] == "TotalCH")
        & (merge_log["valid_sunday"].astype(str) == str(valid_sunday.date()))
        & (when > known_time.tz_convert("UTC"))
    ]
    if hit.empty:
        return d
    first = hit.loc[when[hit.index].idxmin()]
    row = d["valid_time"] == valid_sunday
    d.loc[row, "content_gwh"] = float(first["old_content_gwh"])
    d.loc[row, "max_gwh"] = float(first["old_max_gwh"])
    d.loc[row, "fill"] = round(float(first["old_content_gwh"]) / float(first["old_max_gwh"]), 6)
    return d


def hdd_window(origin_day: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last day of the HDD window of an origin, exactly as features.py takes it:
    the 28 days ending 7 days before the origin day (tested against origin_features)."""
    end = origin_day - pd.Timedelta(days=features.LAG_DAYS)
    return end - pd.Timedelta(days=features.WINDOW_DAYS - 1), end


def late_note(made_at: pd.Timestamp, target_start: pd.Timestamp) -> str:
    """'' for a forecast made before its target window begins (00:00 Europe/Zurich of the
    first delivery day), else a note. Owner's rule of 2026-11-13."""
    if made_at <= pd.Timestamp(target_start.date(), tz=TZ):
        return ""
    return (
        f"late: made after the target window began on {target_start.date()};"
        " inputs as known at known_time"
    )


def _plan(w: dict) -> dict:
    kt = w["first_seen_utc"].tz_convert(TZ)
    od = kt.tz_localize(None).normalize()
    start = features.target_start(kt)
    return {**w, "kt": kt, "od": od, "start": start, "hdd_window": hdd_window(od)}


def forecast(write: bool = True, now: pd.Timestamp | None = None, log=lambda m: None) -> dict:
    """Forecast every live origin that has none, oldest first.

    Each origin uses only what was known at its own known_time: its SFOE value as first
    published (storage_as_known), control windows that end before its origin day, and no
    HDD day after its HDD window. A forecast made after its target window has begun gets
    a `note` that starts with "late" and is reported apart from the on-time forecasts.
    """
    from alpinehydro.fetch import era5
    from alpinehydro.norms import add_norms

    lw = latest_week()
    status = {
        "latest_week": str(lw["valid_sunday"].date()),
        "latest_week_source": lw["source"],
        "made": False,
        "forecasts": [],
        "skipped": [],
        "warnings": [],
    }
    done = load()
    todo = pending_origins(lw["storage"], done)
    if not todo:
        vs = lw["valid_sunday"]
        status["reason"] = (
            "every live origin already has a forecast"
            if len(done)
            else f"latest SFOE week {vs.date()} is not a live origin; the first live origin is"
            f" the week of Sunday {max(next_possible(vs), LIVE_FIRST).date()}, made as soon as"
            " SFOE releases it (PDF or CSV)"
        )
        return status
    plans = []
    for w in todo:
        if w["first_seen_utc"] is None:
            status["skipped"].append(
                {
                    "valid_sunday": str(w["valid_sunday"].date()),
                    "reason": "no first-seen time in the release logs",
                }
            )
        else:
            plans.append(_plan(w))
    spread = features.daily_spread("CH", "DE_LU")
    spread_it = features.daily_spread("CH", "IT_NORD")
    controls = features.daily_controls()
    # Deviation D15: live HDD windows from the CDS (about 6 days late, Earth Engine ~10).
    status["warnings"] += era5.cds_prefetch([p["hdd_window"] for p in plans], log=log)
    m = train() if plans else None
    pc = models.PRIMARY_CONTROLS
    for p in plans:
        vs, kt, od, start = p["valid_sunday"], p["kt"], p["od"], p["start"]
        d = add_norms(storage_as_known(p["storage"], vs, kt), windows=(10,))
        x = float(d.loc[d["valid_time"] == vs, "dev_10y_pp"].iloc[0])
        r = pd.DataFrame(
            [
                {
                    "valid_time": vs,
                    "known_time": kt,
                    "origin_day": od,
                    "target_start": start,
                    "target_end": start + pd.Timedelta(days=features.WINDOW_DAYS - 1),
                    "winter": vs.year - int(vs.month <= 4),
                    "month": vs.month,
                    "dev_10y_pp": x,
                }
            ]
        )
        c = dict(controls)
        for k, country in (("hdd_ch", "CH"), ("hdd_de", "DE")):
            c[k] = era5.hdd_live(country, *p["hdd_window"], hist=controls[k])
        row, _ = features.origin_features(next(r.itertuples()), spread, spread_it, c)
        missing = [k for k in pc if not np.isfinite(row[k])]
        if missing:
            status["skipped"].append(
                {
                    "valid_sunday": str(vs.date()),
                    "reason": f"controls below the 90% coverage floor: {missing}",
                }
            )
            continue
        one = models.clip(
            pd.DataFrame([row]).rename(columns={"dev_10y_pp": "x"}).assign(y=0.0), m["cut"]
        )
        made = pd.Timestamp(now or dt.datetime.now(dt.UTC)).floor("s")
        out = {
            "valid_sunday": str(vs.date()),
            "known_time": kt.isoformat(),
            "known_time_source": p["source"],
            "origin_day": str(od.date()),
            "target_start": str(start.date()),
            "target_end": str(row["target_end"].date()),
            "dev_10y_pp": round(x, 3),
            **{k: round(float(row[k]), 3) for k in pc},
            "forecast_full": round(
                float((models.design(one, pc, True, m["months"]) @ m["full"])[0]), 2
            ),
            "forecast_b3": round(
                float((models.design(one, pc, False, m["months"]) @ m["b3"])[0]), 2
            ),
            "made_at_utc": made.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": m["label"],
            "realised_spread": "",
            "note": late_note(made, start),
        }
        done = pd.concat([done, pd.DataFrame([out])], ignore_index=True)
        if write:
            _write(done)  # after every origin, so a later failure loses nothing
        status["forecasts"].append(out)
    status["made"] = bool(status["forecasts"])
    if status["made"]:
        status["forecast"] = status["forecasts"][-1]
    if status["skipped"]:
        status["reason"] = "; ".join(
            f"{s['valid_sunday']}: {s['reason']}" for s in status["skipped"]
        )
    return status


HEADER = [
    "# Live H1 forecasts, winter 2026/27 (pre-registration section 9). Forecasts and",
    "# their inputs only; realised_spread will hold one derived number per window (the",
    "# mean CH minus DE-LU baseload spread), never a price series. note is empty for a",
    "# forecast made before its target window began and starts with 'late' otherwise;",
    "# late forecasts are reported apart from the on-time ones.",
]


def _write(table: pd.DataFrame, path=OUT) -> bool:
    """Write the table; returns False (and leaves the file) if nothing changed."""
    nl = chr(10)
    text = nl.join(HEADER) + nl + table[COLUMNS].to_csv(index=False, lineterminator=nl)
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return False
    path.write_bytes(text.encode("utf-8"))
    return True


def load(path=OUT) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    t = pd.read_csv(path, comment="#", dtype={"realised_spread": "object", "note": "object"})
    if "note" not in t.columns:  # a table written before 2026-11-13
        t["note"] = ""
    t["note"] = t["note"].fillna("")
    return t


def is_late(table: pd.DataFrame) -> pd.Series:
    return table["note"].astype(str).str.startswith("late")


def needs_forecast(today: pd.Timestamp | None = None) -> bool:
    """True if any live origin (not only the latest SFOE week) has no forecast yet."""
    return bool(pending_origins())


def pending_realised(today: pd.Timestamp, table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Forecast rows whose 28-day window has fully passed and that have no realised value."""
    t = load() if table is None else table
    if t.empty:
        return t
    blank = t["realised_spread"].isna() | (t["realised_spread"].astype(str).str.strip() == "")
    return t[blank & (pd.to_datetime(t["target_end"]) < today.normalize())]


def fill_realised(spread: pd.Series, today: pd.Timestamp, path=OUT) -> dict:
    """Fill realised_spread (mean daily CH minus DE-LU spread, 2 decimals) for every window
    that has fully passed and has all 28 delivery days complete in the price cache."""
    t = load(path)
    todo = pending_realised(today, t)
    filled, waiting = [], []
    for i, r in todo.iterrows():
        days = pd.date_range(r["target_start"], r["target_end"], freq="D")
        got = spread.reindex(days)
        if got.notna().sum() < features.WINDOW_DAYS:
            waiting.append(r["valid_sunday"])
            continue
        t.loc[i, "realised_spread"] = f"{got.mean():.2f}"
        filled.append(r["valid_sunday"])
    changed = _write(t, path) if filled else False
    return {"filled": filled, "waiting_for_prices": waiting, "changed": changed}


def chart(out_dir=config.FIGURES) -> list:
    """Live forecasts (full model and B3) per origin, and the realised spread where known."""
    from alpinehydro.plots import CURRENT, GRID, INK, INK_2, MEDIAN, SURFACE, _save, _style, plt

    t = load()
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    if t.empty:
        ax.text(
            0.5,
            0.5,
            "No live forecast yet. The first origin is the SFOE week of Sunday 1 November 2026.",
            ha="center",
            va="center",
            color=INK_2,
            fontsize=10,
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        x = pd.to_datetime(t["valid_sunday"])
        real = pd.to_numeric(t["realised_spread"], errors="coerce")
        ax.plot(x, t["forecast_full"], "o-", color=CURRENT, lw=1.6, ms=5, label="Full H1 model")
        ax.plot(x, t["forecast_b3"], "s--", color=MEDIAN, lw=1.0, ms=4, label="B3, controls only")
        late = is_late(t)
        if late.any():  # hollow markers: made after the target window began
            kw = {"ls": "none", "mfc": SURFACE, "zorder": 3}
            ax.plot(x[late], t.loc[late, "forecast_full"], "o", color=CURRENT, ms=5, **kw)
            ax.plot(x[late], t.loc[late, "forecast_b3"], "s", color=MEDIAN, ms=4, **kw)
            ax.plot([], [], "o", color=INK_2, mfc=SURFACE, ls="none", ms=5, label="Made late")
        ax.plot(x, real, "D", color=INK, ms=5, label="Realised 28-day mean")
        ax.axhline(0, color=GRID, lw=0.8)
        ax.set_ylabel("CH minus DE-LU, EUR/MWh (28-day mean)", color=INK_2)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2)
    ax.set_title(
        "Live check 2026/27: forecast of the next 28-day spread, by SFOE week",
        loc="left",
        color=INK,
        fontsize=11,
    )
    _style(ax)
    fig.text(
        0.01,
        0.01,
        "Storage: Swiss Federal Office of Energy SFOE. Realised spread: one derived mean per"
        " window from ENTSO-E Transparency Platform day-ahead prices.\nNot part of the no-edge"
        " rule.",
        color=INK_2,
        fontsize=6.5,
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return _save(fig, out_dir, "live_forecasts")
