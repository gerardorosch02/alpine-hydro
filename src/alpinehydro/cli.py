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
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
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


def _hero() -> None:
    from alpinehydro.fetch import sfoe
    from alpinehydro.plots import hero_chart

    for p in hero_chart(sfoe.load_processed()):
        typer.echo(f"wrote {p.relative_to(config.ROOT)}")


@app.command("figures")
def figures():
    """Draw the hero storage chart."""
    _hero()


@app.command("demo")
def demo():
    """Rebuild the hero chart from committed data/processed/ only. No network, no keys."""
    _hero()


@app.command("status")
def status():
    """Show the latest SFOE week, fill and deviation from the norms."""
    from alpinehydro.fetch import sfoe
    from alpinehydro.norms import add_norms

    storage = sfoe.load_processed()
    d = add_norms(storage[storage["region"] == "TotalCH"]).iloc[-1]
    typer.echo(
        f"week ending {d['valid_time'].date()}: fill {d['fill'] * 100:.1f}%, "
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
