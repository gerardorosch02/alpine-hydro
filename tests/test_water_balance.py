"""Water balance (post-hoc, prereg/WATER_BALANCE_PLAN.md): identity, alignment, eta, demo."""

import numpy as np
import pandas as pd
import pytest

from alpinehydro import water_balance as wb
from alpinehydro.fetch import entsoe, sfoe, sfoe_daily


def _synthetic(years=range(2016, 2027), seed=0) -> pd.DataFrame:
    """Weekly table with known flows: inflow and release are chosen, dS follows."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-01-03", "2026-12-27", freq="W-SUN")
    g_res = rng.uniform(50, 150, len(idx))
    g_ps = rng.uniform(10, 40, len(idx))
    pump = rng.uniform(5, 30, len(idx))
    true_inflow = rng.uniform(0, 300, len(idx))
    ds = true_inflow - (g_res + g_ps - wb.ETA * pump)
    w = pd.DataFrame(
        {
            "content_gwh": 1000 + np.cumsum(ds),
            "max_gwh": 8900.0,
            "ds_gwh": ds,
            "g_res_gwh": g_res,
            "g_ps_gwh": g_ps,
            "pumping_gwh": pump,
            "entsoe_gap": False,
            "true_inflow": true_inflow,
        },
        index=idx,
    )
    w["sfoe_speicherkraft_gwh"] = g_res + g_ps
    return wb.use_source(w)


def test_identity_recovers_known_inflow():
    w = _synthetic()
    assert np.allclose(wb.inflow(w), w["true_inflow"])
    assert np.allclose(wb.inflow(w) - wb.release(w), w["ds_gwh"])


def test_decomposition_adds_up_and_labels():
    w = _synthetic()
    # Cut 2026 inflow in its primary window: a pure weather shortfall.
    start, end = wb.window(2026)
    sel = (w.index > start) & (w.index <= end)
    w.loc[sel, "ds_gwh"] -= 40.0
    d = wb.decompose(w, 2026)
    a = d["anomaly"]
    assert a["ds_gwh"] == pytest.approx(a["inflow_gwh"] - a["release_gwh"], abs=0.2)
    assert d["inflow_share"] + d["release_share"] == pytest.approx(1.0, abs=1e-3)
    assert d["label"] == "weather story"
    assert 2026 not in d["baseline_years"]


def test_label_rule():
    assert wb.label_for(0.70, 0.30) == "weather story"
    assert wb.label_for(2 / 3, 1 / 3) == "weather story"
    assert wb.label_for(-0.2, 1.2) == "operator story"
    assert wb.label_for(0.5, 0.5) == "mixed"
    assert wb.label_for(None, None) == "no shortfall"


def test_windows_are_sundays():
    for y in range(2015, 2027):
        for end in ("aug", "sep"):
            s, e = wb.window(y, end)
            assert s.dayofweek == 6 and e.dayofweek == 6
            assert s <= pd.Timestamp(f"{y}-03-31") < s + pd.Timedelta(days=7)
    assert wb.window(2026) == (pd.Timestamp("2026-03-29"), pd.Timestamp("2026-08-30"))
    assert wb.window(2026, "sep")[1] == pd.Timestamp("2026-09-27")


def test_entsoe_week_runs_monday_to_sunday_with_dst():
    # Week of the March 2026 clock change: Monday 23 to Sunday 29 March, 167 hours.
    hours = pd.date_range(
        "2026-03-23", "2026-03-30", freq="1h", tz="Europe/Zurich", inclusive="left"
    )
    s = pd.Series(1000.0, index=hours)  # 1000 MW
    w = entsoe.sfoe_weeks_gwh(s)
    assert list(w.index) == [pd.Timestamp("2026-03-29")]
    assert w["expected_hours"].iloc[0] == 167
    assert w["gwh"].iloc[0] == pytest.approx(167.0)


def test_entsoe_gap_week_below_90_percent():
    hours = pd.date_range(
        "2026-06-01", "2026-06-08", freq="1h", tz="Europe/Zurich", inclusive="left"
    )
    s = pd.Series(500.0, index=hours[:140])  # 140 of 168 hours
    w = entsoe.sfoe_weeks_gwh(s)
    assert bool(w["gap"].iloc[0]) and np.isnan(w["gwh"].iloc[0])
    w = entsoe.sfoe_weeks_gwh(pd.Series(500.0, index=hours[:160]))
    assert w["gwh"].iloc[0] == pytest.approx(500 * 168 / 1000)


def test_daily_pumping_spread_and_week_sum():
    m = pd.DataFrame(
        {"pumping_gwh": [310.0, 300.0]}, index=pd.DatetimeIndex(["2026-08-01", "2026-09-01"])
    )
    d = sfoe_daily.daily_pumping(m)
    assert d.loc["2026-08-15"] == pytest.approx(10.0)
    assert d.loc["2026-09-15"] == pytest.approx(10.0)
    wk = sfoe_daily.sfoe_weeks(d)
    # Monday 31 August to Sunday 6 September: 1 day of August, 6 of September.
    assert wk.loc[pd.Timestamp("2026-09-06"), "gwh"] == pytest.approx(70.0)
    assert (wk.index.dayofweek == 6).all()


def test_committed_weeks_match_sfoe_sunday_readings():
    w = wb.load_weekly()
    st = sfoe.load_processed()
    ch = st[st["region"] == "TotalCH"].set_index("valid_time")
    assert (w.index.dayofweek == 6).all()
    common = w.index.intersection(pd.to_datetime(ch.index))
    assert len(common) == len(w)
    assert np.allclose(w["content_gwh"], ch.loc[w.index, "content_gwh"])
    diff = ch["content_gwh"].diff().reindex(w.index)
    assert np.allclose(w["ds_gwh"].iloc[1:], diff.iloc[1:])


def test_sources_differ_only_in_g():
    w = wb.load_weekly()
    e = wb.use_source(w, "entsoe")
    assert w.attrs["source"] == "sfoe" and e.attrs["source"] == "entsoe"
    assert np.allclose(w["g_gwh"].dropna(), w["sfoe_speicherkraft_gwh"].dropna())
    ok = ~e["gap"]
    assert np.allclose(e.loc[ok, "g_gwh"], e.loc[ok, "g_res_gwh"] + e.loc[ok, "g_ps_gwh"])


def test_eta_robustness_runs_and_moves_inflow_the_right_way():
    w = wb.load_weekly()
    out = {eta: wb.decompose(w, 2022, "aug", eta) for eta in wb.ETAS}
    assert set(out) == {0.70, 0.75, 0.80}
    # A larger eta credits more pumping to storage, so less implied inflow.
    assert out[0.70]["this"]["inflow_gwh"] > out[0.80]["this"]["inflow_gwh"]
    for d in out.values():
        assert d["label"] in {"weather story", "operator story", "mixed", "no shortfall"}


def test_water_balance_figures_build_from_committed_data(tmp_path, monkeypatch):
    """The demo path with no keys and no local price cache: two figures and a clear note."""
    from alpinehydro import plots_water_balance

    monkeypatch.setattr(wb, "PRICE_CACHE", tmp_path / "no_prices.parquet")
    notes = []
    paths = plots_water_balance.all_figures(out_dir=tmp_path, log=notes.append)
    assert sorted(p.name for p in paths) == ["water_balance_2026.png", "water_balance_years.png"]
    assert all(p.stat().st_size > 10_000 for p in paths)
    assert notes == ["release_vs_price skipped: needs local ENTSO-E prices"]


def test_release_anomaly_is_zero_on_average_in_baseline():
    from alpinehydro.plots_water_balance import release_vs_price_table

    w = wb.load_weekly()
    idx = w.index[w.index.month.isin(range(4, 10))]
    t = release_vs_price_table(w, pd.Series(50.0, index=idx))
    base = t[t["year"].between(2015, 2025)]
    assert abs(base["release_anom_gwh"].mean()) < 5.0
