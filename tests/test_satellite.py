"""Tests for the Part A satellite pipeline: Otsu, level matching, curves, weekly alignment."""

import numpy as np
import pandas as pd
import pytest

from alpinehydro import config, hypsometry, storage, water_mask, weekly


def test_otsu_splits_two_peaks():
    rng = np.random.default_rng(0)
    vals = np.concatenate([rng.normal(-0.4, 0.05, 5000), rng.normal(0.5, 0.05, 3000)])
    thr = water_mask.otsu(vals)
    assert -0.2 < thr < 0.3
    assert water_mask.two_peaked(vals, thr)


def test_one_peak_is_not_two_peaked():
    rng = np.random.default_rng(1)
    vals = rng.normal(-0.3, 0.1, 8000)
    assert not water_mask.two_peaked(vals, water_mask.otsu(vals))


def _cone(n=201, slope=0.1):
    """A cone-shaped basin: height grows with distance from the centre (10 m pixels)."""
    y, x = np.mgrid[:n, :n]
    r = np.hypot(x - n // 2, y - n // 2) * hypsometry.RES
    return 100.0 + slope * r


def test_level_matcher_on_a_cone():
    z = _cone()
    seed = z <= z.min() + 1e-9
    join = hypsometry.join_levels(z, seed, np.ones_like(z, bool))
    levels = np.round(np.arange(100, 190, 0.25), 2)
    valid = np.ones_like(z, bool)
    for true in (112.3, 140.0, 171.8):
        water = z <= true
        lvl, iou = storage.iou_level(join, water, valid, levels)
        assert abs(lvl - true) <= 0.5
        assert iou > 0.95
        shore = storage.shoreline_level(z, water, valid, valid)
        assert abs(shore - true) <= 0.5 + hypsometry.RES * 0.1


def test_level_matcher_ignores_cloud():
    z = _cone()
    join = hypsometry.join_levels(z, z <= z.min() + 1e-9, np.ones_like(z, bool))
    levels = np.round(np.arange(100, 190, 0.25), 2)
    water = z <= 150.0
    valid = np.ones_like(z, bool)
    valid[:, :80] = False  # a cloud over the western part
    water_seen = water & valid
    lvl, _ = storage.iou_level(join, water_seen, valid, levels)
    assert abs(lvl - 150.0) <= 0.5


@pytest.mark.parametrize("slug", [r["slug"] for r in config.reservoirs()])
def test_volume_curve(slug):
    path = hypsometry.CURVE_DIR / f"{slug}.csv"
    if not path.exists():
        pytest.skip("curve not built")
    c = hypsometry.load_curve(slug)
    r = hypsometry.reservoir(slug)
    assert (np.diff(c["level_m"]) > 0).all()
    assert (np.diff(c["volume_mm3"]) >= -1e-9).all()
    assert (np.diff(c["area_km2"]) >= -1e-9).all()
    v_full = float(np.interp(r["full_level_m"], c["level_m"], c["volume_mm3"]))
    assert abs(v_full / r["gross_volume_mm3"] - 1) < 0.01


def test_power_fit_meets_area_and_volume():
    fit = hypsometry.fit_below_floor(a_floor=2.0, v_below=100.0, floor=2000.0, bed=1900.0)
    assert 1 <= fit.b <= 4
    assert fit.area(np.array([2000.0]))[0] == pytest.approx(2.0)
    assert fit.volume(np.array([2000.0]))[0] == pytest.approx(100.0)


def test_weekly_alignment_within_three_days():
    weeks = pd.DataFrame(
        {
            "valid_time": pd.to_datetime(["2023-07-16", "2023-07-23", "2023-07-30"]),
            "datum": pd.to_datetime(["2023-07-17", "2023-07-24", "2023-07-31"]),
        }
    )
    weeks["week_end_utc"] = weeks["datum"].dt.tz_localize("Europe/Zurich").dt.tz_convert("UTC")
    t = pd.to_datetime(
        ["2023-07-13 10:30", "2023-07-18 10:30", "2023-07-20 10:30", "2023-07-28 10:30"],
        utc=True,
    )
    scenes = pd.DataFrame(
        {
            "time_utc": t,
            "sensor": "s2",
            "scene_id": ["a", "b", "c", "d"],
            "flag": ["ok", "ok", "cloud", "no_match"],
            "level_m": [1.0, 2.0, 3.0, 4.0],
            "volume_mm3": 1.0,
            "fill": 0.5,
        }
    )
    out = weekly.align(scenes, weeks, 3)
    assert (out["days_from_week_end"].abs() <= 3).all()
    first = out.iloc[0]
    assert first["scene_id"] == "b" and first["status"] == "ok"
    # Week of 23 July: only the cloud scene of the 20th (3.4 days) and the no_match scene
    # of the 28th (4.4 days) exist, both beyond 3 days, so the week is absent.
    assert pd.Timestamp("2023-07-23").date() not in set(out["valid_time"])
    last = out.iloc[-1]
    assert last["scene_id"] == "d" and last["status"] == "no_match"


def test_dahiti_pairs_within_three_days():
    from alpinehydro import dahiti

    scenes = pd.DataFrame(
        {
            "time_utc": ["2024-07-01T10:00:00Z", "2024-07-10T10:00:00Z", "2024-07-20T10:00:00Z"],
            "flag": ["ok", "ok", "cloud"],
            "level_m": [887.5, 887.0, 880.0],
        }
    )
    levels = pd.DataFrame(
        {"date": pd.to_datetime(["2024-07-02", "2024-07-15", "2024-07-20"]), "wse": [887.0] * 3}
    )
    out = dahiti.compare(scenes, levels, 3)
    # Only the scene of 1 July has a DAHITI point within 3 days; the 20 July scene is cloud.
    assert out["n"] == 1
    assert out["mean_difference_m"] == pytest.approx(0.5)
