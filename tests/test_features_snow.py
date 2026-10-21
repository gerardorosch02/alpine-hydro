"""Look-ahead tests for the Part C feature table (H3 analysis plan timing)."""

import numpy as np
import pandas as pd
import pytest

from alpinehydro import features_snow as fs
from alpinehydro.fetch import sfoe


def test_window_mean_uses_only_days_up_to_the_cutoff():
    days = pd.date_range("2020-03-01", "2020-05-31")
    s = pd.Series(np.arange(len(days), dtype=float), index=days)
    end = pd.Timestamp("2020-04-28")
    mean, n, last = fs.window_mean(s, end)
    assert last == end and n == 8
    assert mean == pytest.approx(s.loc["2020-04-21":"2020-04-28"].mean())


def test_window_mean_needs_four_days():
    days = pd.date_range("2020-04-21", "2020-04-28")
    s = pd.Series([1.0, np.nan, np.nan, np.nan, np.nan, np.nan, 2.0, 3.0], index=days)
    mean, n, _ = fs.window_mean(s, pd.Timestamp("2020-04-28"))
    assert n == 3 and np.isnan(mean)


def test_last_sunday_of_september():
    assert fs.last_sunday_september(2026) == pd.Timestamp("2026-09-27")
    assert fs.last_sunday_september(2024) == pd.Timestamp("2024-09-29")
    assert fs.last_sunday_september(2019) == pd.Timestamp("2019-09-29")


def test_starting_storage_was_known_at_the_issue_date():
    st = fs.alpine_total(sfoe.load_processed())
    st = st[st["region"] == "Total"].copy()
    st["valid_time"] = pd.to_datetime(st["valid_time"])
    for y in (2005, 2016, 2022, 2026):
        for m in (4, 5):
            issue = pd.Timestamp(y, m, 1)
            row = fs.starting_storage(st, issue)
            kt = pd.Timestamp(row["known_time"]).tz_convert(fs.TZ)
            assert kt <= pd.Timestamp(y, m, 1, 23, 59, tz=fs.TZ)
            # And it is the latest such week: the next week was not yet known.
            nxt = st[st["valid_time"] > row["valid_time"]].iloc[0]
            assert pd.Timestamp(nxt["known_time"]).tz_convert(fs.TZ) > kt


def test_alpine_total_is_the_sum_of_three_regions():
    raw = sfoe.load_processed()
    st = fs.alpine_total(raw)
    day = pd.Timestamp("2022-09-25")
    parts = raw[(pd.to_datetime(raw["valid_time"]) == day) & raw["region"].isin(fs.snow.CANTONS)]
    tot = st[(pd.to_datetime(st["valid_time"]) == day) & (st["region"] == "Total")]
    assert tot["content_gwh"].iloc[0] == pytest.approx(parts["content_gwh"].sum())
    assert tot["fill"].iloc[0] == pytest.approx(parts["content_gwh"].sum() / parts["max_gwh"].sum())


def _table():
    if not fs.OUT.exists():
        pytest.skip("features_h3.csv not built")
    return fs.load()


def test_every_snow_feature_ends_at_or_before_its_cutoff():
    f = _table()
    issue = pd.to_datetime(f["issue_date"])
    m_last = pd.to_datetime(f["modis_last"])
    e_last = pd.to_datetime(f["era5_last"])
    assert (pd.to_datetime(f["modis_cutoff"]) == issue - pd.Timedelta(days=3)).all()
    assert (pd.to_datetime(f["era5_cutoff"]) == issue - pd.Timedelta(days=7)).all()
    ok_m, ok_e = m_last.notna(), e_last.notna()
    assert (m_last[ok_m] <= issue[ok_m] - pd.Timedelta(days=3)).all()
    assert (e_last[ok_e] <= issue[ok_e] - pd.Timedelta(days=7)).all()


def test_starting_storage_in_table_was_known_at_issue():
    f = _table()
    for _, r in f.dropna(subset=["start_known_time"]).iterrows():
        kt = pd.Timestamp(r["start_known_time"]).tz_convert(fs.TZ)
        d = pd.Timestamp(r["issue_date"])
        assert kt <= pd.Timestamp(d.year, d.month, d.day, 23, 59, tz=fs.TZ)


def test_ten_year_baselines_use_earlier_years_only():
    f = _table()
    assert (f["era5_base_last_year"] == f["year"] - 1).all()
    c0 = f.dropna(subset=["c0_fill_pp"])
    assert (c0["c0_last_year"] == c0["year"] - 1).all()
    # Recompute C0 from the table's own targets for one region: only years Y-10..Y-1.
    t = f[(f["region"] == "Total") & (f["issue"] == "may1") & (f["band_m"] == 1800)]
    t = t.set_index("year")
    for y in (2011, 2020, 2026):
        assert t.loc[y, "c0_fill_pp"] == pytest.approx(t.loc[y - 10 : y - 1, "end_fill_pp"].mean())


def test_c0_is_unchanged_when_future_targets_change():
    raw = sfoe.load_processed()
    st = fs.alpine_total(raw)
    st["valid_time"] = pd.to_datetime(st["valid_time"])
    st = st[st["region"] == "Total"]
    fut = st.copy()
    fut.loc[fut["valid_time"] >= pd.Timestamp("2020-01-01"), "fill"] = 0.0
    a = [fs.targets(st, y)["end_fill_pp"] for y in range(2009, 2019)]
    b = [fs.targets(fut, y)["end_fill_pp"] for y in range(2009, 2019)]
    assert a == b  # the C0 inputs for 2019 do not see 2020 onwards
