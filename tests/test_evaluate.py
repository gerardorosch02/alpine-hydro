"""Unit tests for the H1 models and tests, on synthetic data (no price data)."""

import numpy as np
import pandas as pd
import pytest

from alpinehydro import evaluate, models


def _synthetic(seed=0, slope=-0.3):
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(2015, 2026):
        for vt in pd.date_range(f"{w}-11-01", f"{w + 1}-04-30", freq="W-SUN"):
            od = vt + pd.Timedelta(days=4)
            rows.append(
                {
                    "valid_time": vt,
                    "origin_day": od,
                    "target_start": od + pd.Timedelta(days=2),
                    "target_end": od + pd.Timedelta(days=29),
                    "winter": w,
                    "month": vt.month,
                    "x": rng.normal(0, 8),
                    "last28": rng.normal(5, 3),
                    **{c: rng.normal(0, 1) for c in models.PRIMARY_CONTROLS},
                }
            )
    d = pd.DataFrame(rows)
    d["y"] = 5 + slope * d["x"] + d["fr_nuclear"] + rng.normal(0, 2, len(d))
    d["y_raw"] = d["y"]
    return d


def test_walk_forward_uses_no_test_winter_data():
    d = _synthetic()
    base = models.walk_forward(d, models.PRIMARY_CONTROLS)
    changed = d.copy()
    changed.loc[changed["winter"] == 2023, "y"] += 100
    wf = models.walk_forward(changed, models.PRIMARY_CONTROLS)
    w23 = wf["winter"] == 2023
    assert np.allclose(wf.loc[w23, "full"], base.loc[w23, "full"])
    assert np.allclose(wf.loc[w23, "b0"], base.loc[w23, "b0"])
    assert not np.allclose(
        wf.loc[wf["winter"] == 2024, "full"], base.loc[base["winter"] == 2024, "full"]
    )


def test_every_test_winter_has_six_training_winters():
    o = models.walk_forward(_synthetic(), models.PRIMARY_CONTROLS)
    assert sorted(o["winter"].unique()) == models.TEST_WINTERS
    assert (o["train_winters"] >= 6).all()


def test_in_sample_slope_recovers_the_truth():
    r = evaluate.in_sample(_synthetic(slope=-0.3), models.PRIMARY_CONTROLS)
    assert r["ci95"][0] < -0.3 < r["ci95"][1]
    assert r["se_nw4"] > 0 and r["mde_per10"] > 0


def test_nw_mean_se_matches_iid_formula():
    rng = np.random.default_rng(1)
    f = rng.normal(0, 2, 20000)
    assert evaluate.nw_mean_se(f, 4) == pytest.approx(2 / np.sqrt(20000), rel=0.05)


def test_holm():
    adj = evaluate.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == {"a": 0.03, "c": 0.06, "b": 0.06}


def _fake(cw_p, r2, ci, beats, ex_r2=0.1, ex_slope=-1.0, ex_beats=2, slope=-1.0):
    full = {
        "oos_primary_clipped_y": {
            "clark_west_vs_b3": {"p_one_sided": cw_p},
            "oos_r2": {"b3": r2},
            "winters_full_beats_b3": beats,
        },
        "in_sample": {"ci95": ci, "slope": slope},
    }
    excl = {
        "oos_primary_clipped_y": {"oos_r2": {"b3": ex_r2}, "winters_full_beats_b3": ex_beats},
        "in_sample": {"slope": ex_slope},
    }
    return full, excl


def test_verdict_is_mechanical():
    assert evaluate.verdict(*_fake(0.01, 0.1, [-0.9, -0.3], 4))["verdict"] == "edge"
    v = evaluate.verdict(*_fake(0.20, 0.1, [-0.9, -0.3], 4))
    assert v["verdict"] == "no edge" and v["deciding_lines"] == ["1"]
    v = evaluate.verdict(*_fake(0.20, -0.1, [-0.1, 0.1], 4))
    assert v["verdict"] == "no effect (equivalence)" and v["deciding_lines"] == ["2"]
    v = evaluate.verdict(*_fake(0.01, 0.1, [-0.9, -0.3], 2))
    assert v["verdict"] == "no edge" and v["deciding_lines"] == ["3"]
    v = evaluate.verdict(*_fake(0.01, 0.1, [-0.9, -0.3], 4, ex_slope=0.5))
    assert v["verdict"] == "no edge"
