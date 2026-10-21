"""Look-ahead tests for the H1 feature table (pre-registration timing)."""

import numpy as np
import pandas as pd
import pytest

from alpinehydro import features

TZ = "Europe/Zurich"


def test_thursday_known_time_gives_saturday_window():
    kt = pd.Timestamp("2023-01-12 23:59", tz=TZ)  # Thursday
    start = features.target_start(kt)
    assert start == pd.Timestamp("2023-01-14")  # Friday auction, Saturday delivery
    assert start.day_name() == "Saturday"


def test_known_before_the_auction_uses_the_same_day_auction():
    kt = pd.Timestamp("2023-01-12 09:00", tz=TZ)
    assert features.target_start(kt) == pd.Timestamp("2023-01-13")


def test_climatological_hdd_uses_only_days_before_the_origin():
    days = pd.date_range("2000-01-01", "2030-12-31")
    hdd = pd.Series(days.year.astype(float), index=days)  # HDD equals the year
    origin = pd.Timestamp("2020-01-10")
    clim = features.climatological_hdd(hdd, pd.Timestamp("2020-01-11"), origin)
    # Same calendar days in 2010 to 2019 (2020's are after the origin): mean year 2014.5.
    assert clim == pytest.approx(2014.5)
    # A window that crosses the origin date in the calendar still uses only past years.
    clim2 = features.climatological_hdd(hdd, pd.Timestamp("2020-01-05"), origin)
    assert clim2 < 2020


def _table(realised=False):
    try:
        return features.load(realised)
    except FileNotFoundError:
        pytest.skip("feature table not built (needs local price and control data)")


def test_random_origins_respect_the_preregistered_timing():
    f = _table()
    rng = np.random.default_rng(0)
    rows = f.iloc[rng.choice(len(f), size=min(60, len(f)), replace=False)]
    one = pd.Timedelta(days=1)
    for r in rows.itertuples():
        od = r.origin_day
        kt_day = r.known_time.tz_convert(TZ).tz_localize(None).normalize()
        assert od == kt_day
        # Target starts after known_time: the day after the first auction after it.
        assert r.target_start > kt_day
        assert r.target_end - r.target_start == pd.Timedelta(days=27)
        # French nuclear and German wind end the day before the origin day.
        assert r.fr_nuclear_last <= od - one
        assert r.de_wind_last <= od - one
        # Swiss nuclear and HDD end 7 days before the origin day.
        for k in ("ch_nuclear_last", "hdd_ch_last", "hdd_de_last"):
            assert getattr(r, k) <= od - 7 * one
        # B1 input ends the day before the origin day (deviation D6).
        assert r.last28_last <= od - one
        # The predictor is the reading of the valid Sunday, before known_time.
        assert r.valid_time < kt_day


def test_targets_never_overlap_known_time():
    f = _table()
    kt_day = f["known_time"].dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
    assert (f["target_start"] > kt_day).all()
