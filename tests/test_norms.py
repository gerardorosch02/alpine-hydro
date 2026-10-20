import numpy as np
import pandas as pd
import pytest

from alpinehydro.fetch import sfoe
from alpinehydro.norms import add_norms, past_median_norm


def synthetic(first=2000, last=2026, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sundays = pd.date_range(f"{first}-01-02", f"{last}-12-31", freq="W-SUN")
    fill = (
        0.5
        + 0.3 * np.sin(np.arange(len(sundays)) / 52 * 2 * np.pi)
        + rng.normal(0, 0.05, len(sundays))
    )
    return pd.DataFrame({"valid_time": sundays, "region": "TotalCH", "fill": fill})


def test_norm_is_median_of_previous_ten_years():
    df = synthetic()
    df["norm"] = past_median_norm(df, 10)
    iso = df["valid_time"].dt.isocalendar()
    row = df[(iso["year"] == 2015) & (iso["week"] == 10)].iloc[0]
    past = df[(iso["year"].between(2005, 2014)) & (iso["week"] == 10)]["fill"]
    assert len(past) == 10
    assert row["norm"] == pytest.approx(np.median(past))


def test_norm_needs_full_window():
    df = synthetic()
    df["norm"] = past_median_norm(df, 10)
    iso = df["valid_time"].dt.isocalendar()
    # The data start on 2000-01-02, which is ISO week 52 of 1999, so only 2010 onwards
    # has ten full past years for every week.
    assert df.loc[iso["year"] <= 2008, "norm"].isna().all()
    assert df.loc[iso["year"] >= 2010, "norm"].notna().all()


def _changing_future_never_moves_earlier_norms(df: pd.DataFrame, future_year: int):
    before = add_norms(df)
    changed = df.copy()
    iso_year = changed["valid_time"].dt.isocalendar()["year"]
    changed.loc[iso_year == future_year, "fill"] += 0.37  # a large edit to one year
    after = add_norms(changed)
    earlier = before["iso_year"] <= future_year
    for col in ("norm_10y", "norm_20y"):
        pd.testing.assert_series_equal(before.loc[earlier, col], after.loc[earlier, col])
    # sanity: later norms do move, so the test would catch a leak
    later = before["iso_year"] == future_year + 1
    assert not np.allclose(before.loc[later, "norm_10y"], after.loc[later, "norm_10y"])


def test_no_look_ahead_synthetic():
    _changing_future_never_moves_earlier_norms(synthetic(), 2021)


def test_no_look_ahead_on_committed_sfoe_data():
    storage = sfoe.load_processed()
    total = storage[storage["region"] == "TotalCH"][["valid_time", "region", "fill"]]
    _changing_future_never_moves_earlier_norms(total.reset_index(drop=True), 2024)


def test_week_53_uses_week_52_norm_and_never_enters_norms():
    df = synthetic()
    df = add_norms(df, windows=(10,))
    w53 = df[(df["iso_year"] == 2020) & (df["iso_week"] == 53)].iloc[0]
    w52 = df[(df["iso_year"] == 2020) & (df["iso_week"] == 52)].iloc[0]
    assert w53["norm_10y"] == w52["norm_10y"]
