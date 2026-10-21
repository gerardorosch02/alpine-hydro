from alpinehydro.fetch import sfoe
from alpinehydro.plots import hero_chart, hero_table


def test_hero_chart_builds_from_committed_data(tmp_path):
    paths = hero_chart(sfoe.load_processed(), out_dir=tmp_path)
    assert [p.name for p in paths] == ["hero_storage.png", "hero_storage.svg"]
    assert all(p.stat().st_size > 10_000 for p in paths)


def test_hero_band_covers_full_hydrological_year():
    band, current, latest, cy = hero_table(sfoe.load_processed())
    assert list(band.index) == list(range(52))
    assert (band["lo"] <= band["q25"]).all() and (band["q75"] <= band["hi"]).all()
    assert (band["n"] >= 25).all()


def test_snow_figures_build_from_committed_data(tmp_path):
    from alpinehydro import plots_snow

    paths = plots_snow.all_figures(out_dir=tmp_path)
    assert sorted(p.name for p in paths) == [
        "h3_snow_vs_refill.png",
        "h3a_forecast_vs_actual.png",
        "h3b_scatter.png",
        "snow_tracker.png",
    ]
    assert all(p.stat().st_size > 10_000 for p in paths)
