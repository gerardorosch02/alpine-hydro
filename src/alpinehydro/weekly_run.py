"""`alpinehydro weekly`: the live run for winter 2026/27, safe to repeat.

Order: release log, SFOE values (CSV and PDF merge), snow (MODIS 1800 m, fallback if
MODIS is silent for 7 days), live H1 forecast (only when a new season origin has none),
realised spreads (only for windows that have fully passed), figures, run log.

Every step reports whether it changed a committed file. Figures and the run log are
written only if something changed, so a rerun with nothing new changes nothing.
Steps that need a key (Earth Engine, ENTSO-E, Earthdata) are skipped with a warning when
the key is missing; nothing secret is ever written to the log.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from alpinehydro import config

EE_TAG = "alpinehydro-weekend5"
LOG_MD = config.REPORTS / "weekly_log.md"
CHOICE = config.PROCESSED / "snow" / "fallback_choice.json"
TRACKER = config.PROCESSED / "snow" / "tracker_daily.csv"
SEASON_START_MONTH = 10


# ---------------------------------------------------------------- steps


def step_release(ctx: dict) -> dict:
    from alpinehydro.fetch import sfoe

    r = sfoe.log_release()
    if "pdf_error" in r:
        ctx["warnings"].append(f"SFOE PDF not reachable: {r['pdf_error']}")
    new = bool(r["csv_new_weeks"]) or bool(r.get("pdf_changed"))
    return {**r, "changed": new, "summary": _release_summary(r)}


def _release_summary(r: dict) -> str:
    parts = []
    if r["csv_new_weeks"]:
        parts.append(f"new CSV weeks {', '.join(r['csv_new_weeks'])}")
    if r.get("pdf_changed"):
        parts.append(f"new PDF version {r.get('pdf_filename')}")
    return "; ".join(parts) or "nothing new from SFOE"


def step_sfoe(ctx: dict) -> dict:
    from alpinehydro.fetch import sfoe_pdf

    r = sfoe_pdf.update()
    changed = bool(r["csv_changed"] or r["pdf_changed"] or r["merged_changed"])
    for x in r["merged_replaced_by_csv"]:
        if x["diff_gwh"] != 0:
            ctx["warnings"].append(
                f"CSV replaced a PDF value for {x['week']} {x['region']} "
                f"(difference {x['diff_gwh']:+.0f} GWh)"
            )
    return {
        **r,
        "changed": changed,
        "summary": f"latest week {r['merged_latest_week']} from the {r['merged_latest_source']}"
        f" ({r['merged_pdf_weeks_in_merged']} PDF weeks ahead of the CSV)",
    }


def _season_days(today: pd.Timestamp) -> pd.DatetimeIndex:
    year = today.year if today.month >= SEASON_START_MONTH else today.year - 1
    return pd.date_range(f"{year}-10-01", today - pd.Timedelta(days=1), freq="D")


def build_tracker(modis: pd.DataFrame, today: pd.Timestamp, viirs_loader=None) -> pd.DataFrame:
    """Season-to-date tracker: MODIS, with the corrected fallback after 7 silent days."""
    from alpinehydro import fallback

    days = _season_days(today)
    choice = json.loads(CHOICE.read_text(encoding="utf-8")) if CHOICE.exists() else {}
    fit = choice.get("fit") if choice.get("chosen") else None
    probe = fallback.apply_fallback(modis, None, None, days)
    needs = fit is not None and (
        probe.groupby("region")["source"]
        .apply(lambda s: (s == "missing").rolling(fallback.SWITCH_DAYS).sum().max())
        .max()
        >= fallback.SWITCH_DAYS
    )
    fb = viirs_loader(days[0], days[-1]) if needs and viirs_loader else None
    return fallback.apply_fallback(modis, fb, fit if fb is not None else None, days)


def _write_tracker(t: pd.DataFrame, path: Path = TRACKER) -> bool:
    header = [
        "# Weekly snow tracker, current season, 1800 m band. source: modis, fallback or",
        "# missing. Fallback days (only after 7 days in a row without a valid MODIS day) are",
        "# VIIRS VJ210A1 corrected by a linear fit on the 2024/25 and 2025/26 overlap.",
        "# MODIS: NASA NSIDC DAAC (MOD10A1/MYD10A1 v6.1). VIIRS: NASA NSIDC DAAC (VJ210A1 v2).",
        "# Tracker only: never used in any H3 test.",
    ]
    out = t.assign(date=pd.to_datetime(t["date"]).dt.strftime("%Y-%m-%d"))
    body = out.to_csv(index=False, float_format="%.4f", lineterminator="\n")
    text = "\n".join(header) + "\n" + body
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return False
    path.write_bytes(text.encode("utf-8"))
    return True


def step_snow(ctx: dict) -> dict:
    from alpinehydro import features_snow, snow

    out: dict = {"changed": False}
    if config.has_secret("EE_PROJECT"):
        out.update(snow.update_modis_recent(EE_TAG))
    else:
        ctx["warnings"].append("EE_PROJECT not set: MODIS not updated")
    modis = snow.read_csv(features_snow.MODIS_CSV)
    last = modis.loc[modis["fsc"].notna(), "date"].max()
    if (ctx["today"] - last).days > 4:
        ctx["warnings"].append(f"latest valid MODIS day is {last.date()}")

    def viirs_loader(start, end):
        from alpinehydro.fetch import viirs

        viirs.fetch(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), log=lambda m: None)
        return viirs.series(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    t = build_tracker(modis, ctx["today"], viirs_loader)
    n_fb = int((t["source"] == "fallback").sum())
    if n_fb:
        ctx["warnings"].append(f"{n_fb} region-days in the tracker use the VIIRS fallback")
    if not CHOICE.exists() or not json.loads(CHOICE.read_text(encoding="utf-8")).get("chosen"):
        ctx["warnings"].append("no MODIS fallback is eligible: the tracker relies on MODIS alone")
    tracker_changed = _write_tracker(t)
    out["changed"] = bool(out.get("changed")) or tracker_changed
    out["summary"] = (
        f"MODIS to {last.date()}"
        + (f" ({out.get('modis_new_days', 0)} new days)" if "modis_new_days" in out else "")
        + (f"; {n_fb} fallback region-days" if n_fb else "")
    )
    return out


def _refresh_controls_and_prices() -> None:
    from alpinehydro.fetch import entsoe

    for name in entsoe.GENERATION:
        entsoe.fetch_generation(name, log=lambda m: None)
    entsoe.fetch_prices(log=lambda m: None)
    entsoe.build_tables()


def step_live(ctx: dict) -> dict:
    from alpinehydro import live

    if not live.needs_forecast():
        w = live.latest_week()
        return {
            "changed": False,
            "summary": f"no new season origin (latest week {w['valid_sunday'].date()}); the first"
            " origin is the week of Sunday 1 November 2026",
        }
    if not config.has_secret("ENTSOE_API_KEY"):
        ctx["warnings"].append("ENTSOE_API_KEY not set: live forecast not made")
        return {"changed": False, "summary": "live forecast skipped (no ENTSO-E key)"}
    _refresh_controls_and_prices()
    ctx["prices_refreshed"] = True
    s = live.forecast()
    if not s["made"]:
        ctx["warnings"].append(f"live forecast not made: {s['reason']}")
        return {"changed": False, "summary": f"no forecast: {s['reason']}"}
    f = s["forecast"]
    return {
        "changed": True,
        "summary": f"forecast for origin {f['valid_sunday']}: {f['forecast_full']} EUR/MWh "
        f"(B3 {f['forecast_b3']}), window {f['target_start']} to {f['target_end']}",
    }


def step_realised(ctx: dict) -> dict:
    from alpinehydro import features, live

    todo = live.pending_realised(ctx["today"])
    if todo.empty:
        return {"changed": False, "summary": "no forecast window has fully passed yet"}
    if not config.has_secret("ENTSOE_API_KEY"):
        ctx["warnings"].append("ENTSOE_API_KEY not set: realised spreads not filled")
        return {"changed": False, "summary": "realised spreads skipped (no ENTSO-E key)"}
    if not ctx.get("prices_refreshed"):
        from alpinehydro.fetch import entsoe

        entsoe.fetch_prices(log=lambda m: None)
        entsoe.build_tables()
    r = live.fill_realised(features.daily_spread("CH", "DE_LU"), ctx["today"])
    if r["waiting_for_prices"]:
        ctx["warnings"].append(f"waiting for complete prices: {r['waiting_for_prices']}")
    return {**r, "summary": f"realised spread filled for {r['filled'] or 'no window'}"}


def figures() -> list[Path]:
    import pandas as pd

    from alpinehydro import live, plots, plots_snow, snow, validate
    from alpinehydro.fetch import sfoe_pdf

    wallis = None
    if validate.OUT.exists():
        wallis = pd.read_csv(validate.OUT, comment="#", parse_dates=["valid_time"])
    paths = plots.hero_chart(sfoe_pdf.load_merged(), wallis)
    from alpinehydro import features_snow

    modis = snow.read_csv(features_snow.MODIS_CSV)
    tracker = snow.read_csv(TRACKER) if TRACKER.exists() else None
    paths += plots_snow.snow_tracker(modis, config.FIGURES, tracker)
    paths += live.chart()
    return paths


# ---------------------------------------------------------------- log and orchestration

STEPS: dict[str, Callable[[dict], dict]] = {
    "release log": step_release,
    "SFOE values": step_sfoe,
    "snow": step_snow,
    "live forecast": step_live,
    "realised spreads": step_realised,
}


def _entry(ctx: dict, results: dict, figs: list[Path]) -> str:
    lines = [f"## Run of {ctx['now']}", ""]
    for name, r in results.items():
        lines.append(f"- {name.capitalize()}: {r.get('summary', '')}.")
    if figs:
        names = ", ".join(sorted({p.stem for p in figs}))
        lines.append(f"- Figures rebuilt: {names}.")
    lines.append(
        "- Sources: SFOE ogd17 CSV and weekly PDF; MODIS MOD10A1/MYD10A1 v6.1 (NASA NSIDC,"
        " via Earth Engine); ENTSO-E Transparency Platform (controls and realised spread,"
        " only when needed)."
    )
    if ctx["warnings"]:
        lines.append("- Warnings:")
        lines += [f"  - {w}" for w in ctx["warnings"]]
    else:
        lines.append("- Warnings: none.")
    return "\n".join(lines) + "\n"


def write_log(entry: str, path: Path = LOG_MD) -> None:
    """Newest run first, under a fixed title."""
    title = (
        "# Weekly live log\n\nOne entry per `alpinehydro weekly` run that changed something."
        " Runs that found nothing new leave no entry (see data/interim/logs/ on the laptop).\n"
    )
    old = path.read_text(encoding="utf-8") if path.exists() else title
    head, _, rest = old.partition("\n## ")
    rest = ("## " + rest) if rest else ""
    path.write_bytes((head.rstrip("\n") + "\n\n" + entry + ("\n" + rest if rest else "")).encode())


def run(
    steps: dict[str, Callable[[dict], dict]] | None = None,
    make_figures: Callable[[], list[Path]] = figures,
    log_path: Path = LOG_MD,
    today: pd.Timestamp | None = None,
    echo=print,
) -> dict:
    now = dt.datetime.now(dt.UTC)
    ctx = {
        "today": today or pd.Timestamp(now.date()),
        "now": now.strftime("%Y-%m-%d %H:%M UTC"),
        "warnings": [],
    }
    results = {}
    for name, fn in (steps or STEPS).items():
        try:
            results[name] = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others
            msg = f"{name} failed: {type(exc).__name__}: {str(exc)[:300]}"
            ctx["warnings"].append(msg)
            results[name] = {"changed": False, "summary": "failed (see warnings)"}
        echo(f"{name}: {results[name].get('summary', '')}")
    changed = any(r.get("changed") for r in results.values())
    figs: list[Path] = []
    if changed:
        figs = make_figures()
        write_log(_entry(ctx, results, figs), log_path)
    for w in ctx["warnings"]:
        echo(f"warning: {w}")
    echo("changed: " + ("yes, figures and reports/weekly_log.md updated" if changed else "no"))
    return {"changed": changed, "results": results, "warnings": ctx["warnings"]}
