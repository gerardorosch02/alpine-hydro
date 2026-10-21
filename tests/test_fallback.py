import numpy as np
import pandas as pd

from alpinehydro import fallback

DAYS = pd.date_range("2026-11-01", periods=20, freq="D")
FIT = {r: {"fit_a": 0.1, "fit_b": 0.5} for r in [*fallback.REGIONS3, "Total"]}


def _modis(valid_days):
    rows = [
        {"date": d.date(), "region": r, "band_m": 1800, "fsc": 0.8}
        for d in valid_days
        for r in [*fallback.REGIONS3, "Total"]
    ]
    return pd.DataFrame(rows)


def _fb():
    return pd.DataFrame(
        [{"date": d.date(), "region": r, "fsc": 0.6} for d in DAYS for r in fallback.REGIONS3]
        + [{"date": d.date(), "region": "Total", "fsc": 0.6} for d in DAYS]
    )


def test_fallback_only_after_seven_days_without_modis():
    # MODIS valid on days 0-4, missing on days 5-19.
    out = fallback.apply_fallback(_modis(DAYS[:5]), _fb(), FIT, DAYS)
    w = out[out["region"] == "Wallis"].reset_index(drop=True)
    assert list(w["source"][:5]) == ["modis"] * 5
    assert list(w["source"][5:11]) == ["missing"] * 6  # 6 missing days: not yet
    assert (w["source"][11:] == "fallback").all()  # the 7th day in a row and after
    assert np.allclose(w["fsc"][11:], 0.1 + 0.5 * 0.6)


def test_short_gap_never_uses_fallback_and_modis_returns():
    valid = list(DAYS[:5]) + list(DAYS[11:])  # 6-day gap
    out = fallback.apply_fallback(_modis(valid), _fb(), FIT, DAYS)
    assert "fallback" not in set(out["source"])
    valid = list(DAYS[:3]) + list(DAYS[15:])  # 12-day gap, then MODIS is back
    w = fallback.apply_fallback(_modis(valid), _fb(), FIT, DAYS).query("region == 'Tessin'")
    src = list(w["source"])
    assert src[15:] == ["modis"] * 5
    assert src[9:15] == ["fallback"] * 6


def test_no_fallback_chosen_leaves_gaps_missing():
    out = fallback.apply_fallback(_modis(DAYS[:2]), None, None, DAYS)
    assert set(out["source"]) == {"modis", "missing"}


def test_selection_rule():
    r = fallback.select(
        {
            "viirs": {"corr": 0.95, "mad": 0.05, "lag_days": 2},
            "hrsi": {"corr": 0.97, "mad": 0.03, "lag_days": 1},
        }
    )
    assert r["chosen"] == "hrsi"
    r = fallback.select(
        {
            "viirs": {"corr": 0.95, "mad": 0.05, "lag_days": 2},
            "hrsi": {"corr": 0.97, "mad": 0.03, "lag_days": 9},  # too late
        }
    )
    assert r["chosen"] == "viirs"
    r = fallback.select({"viirs": {"corr": 0.85, "mad": 0.01, "lag_days": 1}, "hrsi": None})
    assert r["chosen"] is None
    assert "correlation" in r["candidates"]["viirs"]["why"]


def test_gap_fill_expires_after_eight_days_and_70_percent_rule():
    mask = {"Wallis": np.ones((2, 5), bool)}
    full = np.full((2, 5), 0.5, dtype="float32")
    days = pd.date_range("2026-01-01", periods=11)

    def load(d):
        return full if d == days[0] else None

    s = fallback.daily_series(list(days), load, mask)
    w = s[s["region"] == "Wallis"].reset_index(drop=True)
    assert (w["fsc"][:9] == 0.5).all()  # day 0 plus 8 filled days
    assert w["missing"][9] and w["missing"][10]

    part = full.copy()
    part[:, :2] = np.nan  # 60% valid
    s = fallback.daily_series([days[0]], lambda d: part, mask)
    assert s.query("region == 'Wallis'")["missing"].iloc[0]
