"""Command line interface: uv run alpinehydro <command>."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from alpinehydro import config

# Never show local variables in tracebacks: they could hold an API key.
app = typer.Typer(
    add_completion=False, no_args_is_help=True, help=__doc__, pretty_exceptions_show_locals=False
)
CHECKS = config.REPORTS / "checks"


def _write_check(name: str, data: dict) -> Path:
    CHECKS.mkdir(parents=True, exist_ok=True)
    path = CHECKS / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    return path


@app.command("fetch-sfoe")
def fetch_sfoe(refresh: bool = typer.Option(False, help="Download again even if cached.")):
    """Download SFOE storage and write data/processed/sfoe_storage_weekly.csv."""
    from alpinehydro.fetch import sfoe

    df, changed = sfoe.fetch(refresh=refresh)
    total = df[df["region"] == "TotalCH"]
    typer.echo(
        f"{len(df)} rows, {total['valid_time'].min().date()} to "
        f"{total['valid_time'].max().date()}; file {'updated' if changed else 'unchanged'}"
    )


@app.command("log-release")
def log_release():
    """Poll the SFOE CSV and weekly PDF and record when anything new first appears."""
    from alpinehydro.fetch import sfoe

    typer.echo(json.dumps(sfoe.log_release(), indent=2))


@app.command("sfoe-update")
def sfoe_update(refresh: bool = typer.Option(False, help="Download the CSV again.")):
    """Parse the cached weekly PDF, cross-check it against the CSV and merge the two."""
    from alpinehydro.fetch import sfoe_pdf

    typer.echo(json.dumps(sfoe_pdf.update(refresh_csv=refresh), indent=2))


@app.command("hero")
def hero_cmd():
    """Rebuild the hero storage chart from committed files only (no keys)."""
    import pandas as pd

    from alpinehydro import plots, validate
    from alpinehydro.fetch import sfoe_pdf

    wallis = None
    if validate.OUT.exists():
        wallis = pd.read_csv(validate.OUT, comment="#", parse_dates=["valid_time"])
    for p in plots.hero_chart(sfoe_pdf.load_merged(), wallis):
        typer.echo(f"wrote {p.relative_to(config.ROOT)}")


@app.command("weekly")
def weekly_live_cmd():
    """Live run: release log, SFOE merge, snow, live forecast, realised spreads, figures, log.

    Safe to repeat: if nothing is new, no file changes.
    """
    from alpinehydro import weekly_run

    r = weekly_run.run(echo=typer.echo)
    if any("failed" in w for w in r["warnings"]):
        raise typer.Exit(2)


@app.command("safe-commit")
def safe_commit_cmd(message: str = typer.Option(..., "--message", "-m")):
    """Commit only the weekly-run allowlist; abort (exit 3) if anything else changed."""
    from alpinehydro import safe_commit

    r = safe_commit.commit(config.ROOT, message)
    typer.echo(json.dumps(r))
    if not r["committed"] and r["reason"].startswith("aborted"):
        raise typer.Exit(3)


@app.command("fallback-evaluate")
def fallback_evaluate_cmd():
    """Build the VIIRS VJ210A1 series on the overlap winters and apply the fixed rule."""
    import pandas as pd

    from alpinehydro import fallback, features_snow, snow
    from alpinehydro.fetch import viirs

    parts = [viirs.series(s, e) for s, e in fallback.OVERLAP_SEASONS]
    v = pd.concat(parts, ignore_index=True)
    viirs.write(v)
    modis = snow.read_csv(features_snow.MODIS_CSV)
    cmp = fallback.compare(v, modis)
    lag = viirs.publication_lag_days()
    min_corr = min(cmp["per_region"][r]["corr"] for r in fallback.REGIONS3)
    res = {
        "viirs_vj210a1": {
            "corr": min_corr,
            "mad": cmp["pooled_three_cantons"]["mad"],
            "lag_days": lag["median_days"],
        }
    }
    sel = fallback.select(res)
    out = {
        "rule": "eligible if the lowest per-canton correlation >= 0.9 and median publication"
        " lag <= 5 days; lowest pooled MAD wins (deviations W1-W3)",
        "comparison": cmp,
        "publication_lag": lag,
        "selection": sel,
        "chosen": sel["chosen"],
        "fit": {r: cmp["per_region"][r] for r in [*fallback.REGIONS3, "Total"]}
        if sel["chosen"]
        else None,
        "product": "NSIDC VJ210A1 v2 (NOAA-21 VIIRS)",
        "credit": viirs.CREDIT,
    }
    path = config.PROCESSED / "snow" / "fallback_choice.json"
    path.write_bytes((json.dumps(out, indent=2) + "\n").encode("utf-8"))
    _write_check("modis_fallback", out)
    typer.echo(json.dumps(out["selection"], indent=2))


@app.command("fetch-entsoe")
def fetch_entsoe(
    zones: list[str] = typer.Option(None, help="Zones, default from config."),
    refresh: bool = typer.Option(False, help="Refetch cached months."),
):
    """Fetch ENTSO-E day-ahead prices into data/raw/ and build data/interim/ tables."""
    from alpinehydro.fetch import entsoe

    entsoe.fetch_prices(zones, refresh=refresh, log=lambda m: None)
    typer.echo(json.dumps(entsoe.build_tables(zones)))


@app.command("check-reservoir")
def check_reservoir():
    """Compare ENTSO-E's CH reservoir series with SFOE TotalCH (stats only)."""
    from alpinehydro.fetch import entsoe, sfoe

    s = entsoe.fetch_reservoir("CH")
    storage = sfoe.load_processed()
    stats = entsoe.compare_reservoir_with_sfoe(s, storage[storage["region"] == "TotalCH"])
    typer.echo(f"wrote {_write_check('entsoe_reservoir_vs_sfoe', stats)}")


@app.command("fetch-smard")
def fetch_smard(refresh: bool = typer.Option(False)):
    """Fetch SMARD prices and cross-check them against ENTSO-E (stats only)."""
    import pandas as pd

    from alpinehydro.fetch import smard

    s = smard.fetch_all(refresh=refresh)
    e = pd.read_parquet(config.INTERIM / "entsoe_prices_hourly.parquet")
    stats = smard.cross_check(s, e)
    typer.echo(f"wrote {_write_check('smard_vs_entsoe', stats)}")


@app.command("timing")
def timing():
    """Timing-ceiling check from SFOE data only (no prices)."""
    from alpinehydro.fetch import sfoe
    from alpinehydro.norms import add_norms
    from alpinehydro.timing import timing_ceiling

    hyp = config.pipeline()["hypothesis"]
    storage = sfoe.load_processed()
    d = add_norms(storage[storage["region"] == "TotalCH"])
    out = {}
    for col in ("dev_10y_pp", "dev_20y_pp"):
        out[col] = timing_ceiling(
            d,
            col,
            hyp["season_months"],
            hyp["satellite_head_start_days"],
            hyp["sesoi_eur_per_10pp"],
        ).as_dict()
    typer.echo(json.dumps(out, indent=2))
    typer.echo(f"wrote {_write_check('timing_ceiling', out)}")


def _slugs(only: list[str] | None) -> list[str]:
    return only or [r["slug"] for r in config.reservoirs()]


@app.command("outlines")
def outlines_cmd(
    only: list[str] = typer.Option(None, "--only", help="Reservoir slugs, default all."),
    jrc: bool = typer.Option(True, help="Cross-check with JRC max_extent in Earth Engine."),
):
    """Build swissTLM3D outlines and 300 m windows; cross-check with JRC surface water."""
    from alpinehydro import outlines

    out = {}
    for slug in _slugs(only):
        out[slug] = outlines.build(slug)
        if jrc:
            out[slug]["jrc"] = outlines.jrc_check(slug)
        typer.echo(json.dumps(out[slug], ensure_ascii=True))
    if jrc and not only:
        typer.echo(f"wrote {_write_check('outlines_jrc', out)}")


@app.command("curves")
def curves_cmd(
    only: list[str] = typer.Option(None, "--only", help="Reservoir slugs, default all."),
    refresh: bool = typer.Option(False, help="Rebuild the terrain grid and flooding."),
):
    """Build the level-area-volume curves (swissALTI3D plus a global DEM below its floor)."""
    from alpinehydro import hypsometry

    out = {}
    for slug in _slugs(only):
        info = hypsometry.build(slug, refresh=refresh)
        out[slug] = {
            k: info[k]
            for k in (
                "floor_m",
                "global_dem",
                "global_floor_m",
                "global_dem_candidates",
                "usable_share_swissalti3d_2m",
                "usable_share_global_dem_30m",
                "usable_share_fitted",
                "h0_m",
                "b",
                "b_bound_hit",
                "fit_method",
            )
        }
        typer.echo(f"{slug}: global DEM {info['global_dem']}, b {info['b']}, {info['fit_method']}")
    if not only:
        typer.echo(f"wrote {_write_check('curves_global_dem', out)}")


@app.command("masks")
def masks_cmd(
    only: list[str] = typer.Option(None, "--only", help="Reservoir slugs, default all."),
    refresh: bool = typer.Option(False, help="Recompute the candidate list."),
):
    """Earth Engine batch: clear fraction per scene, then pull arrays for clear scenes."""
    from alpinehydro import water_mask

    s = water_mask.settings()
    for slug in _slugs(only):
        cands = water_mask.candidates(slug, refresh=refresh)
        keep = cands[cands["clear_fraction"] >= s["min_clear_fraction"]]
        typer.echo(f"{slug}: {len(cands)} scenes, {len(keep)} at least 90% clear")
        for i, r in enumerate(keep.itertuples(), 1):
            try:
                water_mask.pull(slug, r.sensor, r.date, r.sun_azimuth, r.sun_zenith)
            except Exception as e:  # keep going; the scene is retried on the next run
                typer.echo(f"  {r.sensor} {r.date} failed: {str(e)[:200]}")
            if i % 25 == 0:
                typer.echo(f"  {i}/{len(keep)}")


SATELLITE_SLUGS = ["sihlsee", "gruyere", "dix", "emosson", "mauvoisin"]


@app.command("scenes")
def scenes_cmd(only: list[str] = typer.Option(None, "--only", help="Reservoir slugs.")):
    """Scene tables from the cached masks, merged into data/processed/satellite/scenes.csv."""
    from alpinehydro import storage

    for slug in only or SATELLITE_SLUGS:
        df = storage.build(slug)
        typer.echo(f"{slug}: {len(df)} scenes, {(df['flag'] == 'ok').sum()} ok")
    typer.echo(f"wrote {storage.write_scenes().relative_to(config.ROOT)}")


@app.command("satellite-weekly")
def satellite_weekly_cmd():
    """Weekly series aligned to the SFOE week end: data/processed/satellite/weekly.csv."""
    from alpinehydro import weekly

    df = weekly.build(SATELLITE_SLUGS)
    typer.echo(f"wrote {len(df)} rows to {weekly.OUT.relative_to(config.ROOT)}")


@app.command("validate")
def validate_cmd():
    """Score satellite Wallis against SFOE Wallis, with and without Mauvoisin."""
    from alpinehydro import validate

    main = validate.run(write=True)
    sens = validate.run(["dix", "emosson"])
    out = {"main": main, "sensitivity_without_mauvoisin": sens}
    _write_check("wallis_validation", out)
    for label, m in out.items():
        typer.echo(
            f"{label}: R2 {m.get('r2')} ({'pass' if m['pass'] else 'fail'}), "
            f"MAE {m.get('mae_pp')} pp, bias {m.get('bias_pp')} pp, n {m.get('n')}"
        )


def _figures(example: bool) -> None:
    import pandas as pd

    from alpinehydro import plots, storage, validate
    from alpinehydro.fetch import sfoe

    st = sfoe.load_processed()
    sc = storage.load_scenes()
    wallis_path = validate.OUT
    wallis = None
    paths = []
    if wallis_path.exists():
        wallis = pd.read_csv(wallis_path, comment="#", parse_dates=["valid_time"])
        scored = wallis.dropna(subset=["sat_anom_pp", "sfoe_anom_pp"])
        m = validate.metrics(scored)
        m["pass"] = bool(m.get("r2", -1) >= validate.PASS_R2)
        paths += plots.validation_scatter(wallis, m)
    from alpinehydro.fetch import sfoe_pdf

    paths += plots.hero_chart(sfoe_pdf.load_merged(), wallis)
    slugs = list(dict.fromkeys(sc["reservoir"]))
    order = [s for s in SATELLITE_SLUGS if s in slugs]
    paths += plots.coverage_map(plots.coverage_table(sc, st, order))
    paths += plots.sihlsee_showcase(sc)
    for slug in order:
        paths += plots.reservoir_chart(slug, sc, st)
    if example:
        ok = sc[(sc["reservoir"] == "dix") & (sc["flag"] == "ok") & (sc["sensor"] == "s2")]
        best = ok.sort_values("clear_fraction", ascending=False).iloc[0]
        paths += plots.example_scene("dix", best)
    for p in paths:
        typer.echo(f"wrote {p.relative_to(config.ROOT)}")


@app.command("figures")
def figures():
    """Draw every figure, including the Dix example scene (needs Earth Engine)."""
    _figures(example=True)


@app.command("demo")
def demo():
    """Rebuild the figures from committed data/processed/ only. No network, no keys.

    The Dix example scene needs imagery, so the committed PNG is kept as it is.
    """
    _figures(example=False)
    from alpinehydro import plots_snow

    for p in plots_snow.all_figures():
        typer.echo(f"wrote {p.relative_to(config.ROOT)}")


@app.command("features")
def features_cmd():
    """Build the point-in-time H1 feature tables (data/interim/, never committed)."""
    from alpinehydro import features

    f, fr = features.build()
    typer.echo(f"{len(f)} origins written to {features.OUT.relative_to(config.ROOT)}")


@app.command("h1")
def h1_cmd():
    """Run every pre-registered H1 test, H2, and print the mechanical verdict."""
    from alpinehydro import evaluate

    r = evaluate.run()
    v = r["verdict"]
    typer.echo(f"verdict: {v['verdict']}")
    for k, line in v["lines"].items():
        mark = "HOLDS" if line["holds"] else "does not hold"
        typer.echo(f"  rule line {k} {mark}: {line['values']}")
    for path in evaluate.figures(r):
        typer.echo(f"wrote {path.relative_to(config.ROOT)}")


@app.command("snow-outlines")
def snow_outlines_cmd():
    """Canton outlines (swissBOUNDARIES3D) and 1800/2000 m band areas and polygons (EE)."""
    from alpinehydro import snow

    typer.echo(json.dumps(snow.build_outlines()))
    areas = snow.mask_areas()
    _write_check("snow_masks", {"rows": areas.round(3).to_dict(orient="records")})
    typer.echo(f"wrote {snow.build_band_polygons().relative_to(config.ROOT)}")


@app.command("snow-series")
def snow_series_cmd(
    source: str = typer.Argument(..., help="modis or era5"),
    first_year: int = typer.Option(None),
    last_year: int = typer.Option(None),
    band: int = typer.Option(None, help="MODIS: one band only (1800 or 2000)."),
    spring: bool = typer.Option(False, help="MODIS: only 14 March to 5 May of each year."),
):
    """Pull daily regional snow series year by year (Earth Engine, region statistics only).

    Each year is cached in data/interim/snow/, so a stopped run resumes; the combined
    table is written to data/processed/snow/.
    """
    import datetime as dt

    import pandas as pd

    from alpinehydro import features_snow, snow

    cache = config.INTERIM / "snow"
    cache.mkdir(parents=True, exist_ok=True)
    # Stop after the last day with an image, so no day is only carried forward.
    today = snow.latest_image_day(source) + pd.Timedelta(days=1)
    start = pd.Timestamp(snow.MODIS_START if source == "modis" else snow.ERA5_START)
    years = range(first_year or start.year, (last_year or today.year) + 1)
    for y in years:
        tag = f"{source}{'_' + str(band) if band else ''}{'_spring' if spring else ''}"
        path = cache / f"{tag}_{y}.csv"
        if path.exists() and y < today.year:
            continue
        if spring:
            lo, hi = (pd.Timestamp(f"{y}-{md}") for md in snow.SPRING_WINDOW)
        else:
            lo, hi = pd.Timestamp(y, 1, 1), pd.Timestamp(y + 1, 1, 1)
        s = max(start, lo).strftime("%Y-%m-%d")
        e = min(hi, today).strftime("%Y-%m-%d")
        if s >= e:
            continue
        if source == "modis":
            df = snow.modis_daily(s, e, bands=(band,) if band else snow.BANDS_M)
        else:
            df = snow.era5_swe_daily(s, e)
        df.to_csv(path, index=False)
        typer.echo(f"{source} {y}: {len(df)} rows at {dt.datetime.now():%H:%M}")
    parts = sorted(cache.glob(f"{source}_*.csv"))
    df = pd.concat([pd.read_csv(p) for p in parts], ignore_index=True)
    df = df.drop_duplicates(["date", "region", "band_m"], keep="last")
    stamp = f"pulled_utc: {snow.today_utc()}; Earth Engine workload tag {snow.EE_TAG}"
    if source == "modis":
        snow.write_modis_table()
        out = features_snow.MODIS_CSV
    else:
        out = snow.write_csv(
            df,
            features_snow.ERA5_CSV,
            [
                snow.ERA5_CREDIT,
                "swe_mm: ERA5-Land snow_depth_water_equivalent daily mean (DAILY_AGGR), mm,",
                "averaged over the 500 m band pixels of each canton (same pixels as MODIS).",
                stamp,
            ],
        )
    typer.echo(f"wrote {out.relative_to(config.ROOT)} ({len(df)} rows)")


@app.command("snow-features")
def snow_features_cmd():
    """Build the H3 features and targets, and the yearly H3b target (needs cached prices)."""
    from alpinehydro import features_snow

    f = features_snow.build(*features_snow.load_inputs())
    q4 = None
    if (config.INTERIM / "entsoe_prices_daily.parquet").exists():
        q4 = features_snow.q4_spread()
    for p in features_snow.write(f, q4):
        typer.echo(f"wrote {p.relative_to(config.ROOT)}")


@app.command("h3")
def h3_cmd():
    """Run H3a, H3b and the Holm update exactly as the H3 analysis plan."""
    from alpinehydro import evaluate_snow, plots_snow

    r = evaluate_snow.run()
    p = r["primary"]["walk_forward"]
    typer.echo(
        f"H3a verdict: {r['verdict']} (skill vs C1 {p['skill_vs_c1']:+.3f}, vs C0 "
        f"{p['skill_vs_c0']:+.3f}, CW p {p['clark_west_vs_c1']['p_one_sided']:.3f}, Holm "
        f"{r['holm']['adjusted_p']['H3a']:.3f})"
    )
    for path in plots_snow.all_figures():
        typer.echo(f"wrote {path.relative_to(config.ROOT)}")


@app.command("live-forecast")
def live_forecast_cmd():
    """Live check 2026/27: forecast the next 28-day CH minus DE-LU spread if a new origin."""
    from alpinehydro import live

    s = live.forecast()
    if s["made"]:
        f = s["forecast"]
        typer.echo(
            f"origin {f['valid_sunday']}: forecast {f['forecast_full']} EUR/MWh for "
            f"{f['target_start']} to {f['target_end']} (B3 {f['forecast_b3']})"
        )
    else:
        typer.echo(f"no forecast made: {s['reason']}")


@app.command("status")
def status():
    """Show the latest SFOE week (CSV or newer PDF), fill and deviation from the norms."""
    from alpinehydro.fetch import sfoe_pdf
    from alpinehydro.norms import add_norms

    storage = sfoe_pdf.load_merged()
    d = add_norms(storage[storage["region"] == "TotalCH"]).iloc[-1]
    typer.echo(
        f"week ending {d['valid_time'].date()} ({d['source']}): fill {d['fill'] * 100:.1f}%, "
        f"10y norm {d['norm_10y'] * 100:.1f}% ({d['dev_10y_pp']:+.1f} pp), "
        f"20y norm {d['norm_20y'] * 100:.1f}% ({d['dev_20y_pp']:+.1f} pp)"
    )


@app.command("check-repo")
def check_repo():
    """Fail if any raw, interim or price file is tracked by Git."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=config.ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [
        f
        for f in tracked
        if (
            f.startswith(("data/raw/", "data/interim/", "data/external/"))
            and not f.endswith(".gitkeep")
            and not (f.startswith("data/external/outlines/") and f.endswith((".geojson", ".md")))
        )
        or (f.startswith("data/processed/") and any(k in f.lower() for k in ("price", "entsoe")))
        or f.endswith(".env")
    ]
    if bad:
        typer.echo("Tracked files that must not be in Git:\n" + "\n".join(bad))
        raise typer.Exit(1)
    typer.echo(f"ok: {len(tracked)} tracked files, none raw, interim or price data")


if __name__ == "__main__":
    app()
