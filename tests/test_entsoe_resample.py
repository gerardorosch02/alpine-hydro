import numpy as np
import pandas as pd
import pytest

from alpinehydro.fetch.entsoe import area_for, daily_baseload, to_hourly, weekly_baseload

TZ = "Europe/Zurich"


def series(start: str, end: str, freq: str, value=None) -> pd.Series:
    idx = pd.date_range(
        pd.Timestamp(start, tz=TZ), pd.Timestamp(end, tz=TZ), freq=freq, inclusive="left"
    )
    vals = np.arange(len(idx), dtype=float) if value is None else np.full(len(idx), value)
    return pd.Series(vals, index=idx.tz_convert("UTC"))


def test_quarter_hours_become_hourly_means():
    s = series("2025-10-02", "2025-10-03", "15min")
    h = to_hourly(s)
    assert len(h) == 24
    assert (h["n_values"] == 4).all()
    assert h["price"].iloc[0] == pytest.approx(np.mean([0, 1, 2, 3]))


def test_autumn_clock_change_day_has_25_hours():
    h = to_hourly(series("2025-10-26", "2025-10-27", "15min", value=50.0))
    d = daily_baseload(h)
    row = d[d["valid_time"] == pd.Timestamp("2025-10-26")].iloc[0]
    assert row["n_hours"] == 25 and row["expected_hours"] == 25 and row["complete"]
    assert row["baseload"] == pytest.approx(50.0)


def test_spring_clock_change_day_has_23_hours():
    h = to_hourly(series("2026-03-29", "2026-03-30", "1h", value=10.0))
    d = daily_baseload(h)
    row = d.iloc[0]
    assert row["n_hours"] == 23 and row["expected_hours"] == 23 and row["complete"]


def test_switch_from_hourly_to_quarter_hourly():
    s = pd.concat(
        [
            series("2025-09-30", "2025-10-01", "1h", 40.0),
            series("2025-10-01", "2025-10-02", "15min", 60.0),
        ]
    )
    d = daily_baseload(to_hourly(s))
    assert list(d["baseload"]) == [40.0, 60.0]
    assert d["complete"].all()


def test_known_time_is_day_before_at_13():
    d = daily_baseload(to_hourly(series("2026-01-10", "2026-01-11", "1h", 1.0)))
    assert d["known_time"].iloc[0].isoformat() == "2026-01-09T13:00:00+01:00"


def test_weekly_baseload_covers_monday_to_sunday_with_clock_change():
    h = to_hourly(series("2025-10-20", "2025-10-27", "1h", 5.0))
    w = weekly_baseload(h)
    assert len(w) == 1
    row = w.iloc[0]
    assert row["week_start"] == pd.Timestamp("2025-10-20")
    assert row["valid_time"] == pd.Timestamp("2025-10-26")
    assert row["n_hours"] == 169 and row["complete"]


def test_de_area_before_and_after_split():
    assert area_for("DE_LU", pd.Timestamp("2018-09-01", tz=TZ)) == "DE_AT_LU"
    assert area_for("DE_LU", pd.Timestamp("2018-10-01", tz=TZ)) == "DE_LU"
    assert area_for("CH", pd.Timestamp("2015-01-01", tz=TZ)) == "CH"
