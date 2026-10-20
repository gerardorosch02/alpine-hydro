import math

import pandas as pd
import pytest

from alpinehydro.timing import first_usable_delivery_day, timing_ceiling


def test_thursday_night_release_is_used_by_friday_auction_for_saturday():
    kt = pd.Timestamp("2026-10-15 23:59", tz="Europe/Zurich")  # Thursday
    assert first_usable_delivery_day(kt) == pd.Timestamp("2026-10-17")  # Saturday


def test_release_before_auction_is_used_same_day():
    kt = pd.Timestamp("2026-10-13 09:48", tz="UTC")  # 11:48 Zurich, after 11:00
    assert first_usable_delivery_day(kt) == pd.Timestamp("2026-10-15")
    kt = pd.Timestamp("2026-10-13 10:30", tz="Europe/Zurich")
    assert first_usable_delivery_day(kt) == pd.Timestamp("2026-10-14")


def test_ceiling_arithmetic():
    sundays = pd.date_range("2020-11-01", periods=6, freq="W-SUN")
    dev = [0.0, 2.0, 0.0, 2.0, 0.0, 2.0]  # changes +2, -2, +2, -2, +2
    df = pd.DataFrame({"valid_time": sundays, "dev": dev})
    c = timing_ceiling(df, "dev", [11, 12], head_start_days=4, sesoi_eur_per_10pp=2.0)
    sd = pd.Series([2.0, -2.0, 2.0, -2.0, 2.0]).std(ddof=1)
    assert c.n_weeks == 5
    assert c.sd_weekly_change_pp == pytest.approx(sd)
    assert c.ceiling_linear_eur == pytest.approx(sd * 4 / 7 * 0.2)
    assert c.ceiling_sqrt_eur == pytest.approx(sd * math.sqrt(4 / 7) * 0.2)


def test_ceiling_skips_gaps_and_out_of_season_weeks():
    sundays = list(pd.date_range("2020-10-04", periods=4, freq="W-SUN"))  # Oct weeks
    sundays += [pd.Timestamp("2020-11-29"), pd.Timestamp("2020-12-13")]  # 14-day gap
    df = pd.DataFrame({"valid_time": sundays, "dev": [0, 9, 0, 9, 0, 9]})
    with pytest.raises(ValueError):
        timing_ceiling(df, "dev", [11, 12], 4, 2.0)  # no valid 7-day pair in season
