"""H1 tests and the mechanical no-edge verdict, as pre-registered (plus exploratory H2).

Every test of section 4 of prereg/PREREGISTRATION.md (tag v0.1-prereg) is computed here.
Clarifications of open points are listed as deviations D1 to D10 in reports/results.md.
Output: reports/checks/h1_results.json (statistics only, no price series).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from alpinehydro import config, models

NW_LAG = 4
NW_LAG_ROBUST = 8
HLN_H = 4
EQUIV_PER_POINT = 0.2  # EUR/MWh per point = EUR 2/MWh per 10 points
N_BOOT = 2000
SEED = 20261021
OUT = config.ROOT / "reports" / "checks" / "h1_results.json"


# ---------------------------------------------------------------- building blocks


def nw_cov(X: np.ndarray, resid: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West (Bartlett) covariance of OLS coefficients."""
    n = len(resid)
    xu = X * resid[:, None]
    s = xu.T @ xu
    for j in range(1, lag + 1):
        w = 1 - j / (lag + 1)
        g = xu[j:].T @ xu[:-j]
        s += w * (g + g.T)
    inv = np.linalg.inv(X.T @ X)
    return inv @ s @ inv * n / (n - X.shape[1])


def nw_mean_se(f: np.ndarray, lag: int) -> float:
    """Newey-West standard error of the mean of a series."""
    u = f - f.mean()
    n = len(u)
    lrv = u @ u / n
    for j in range(1, lag + 1):
        lrv += 2 * (1 - j / (lag + 1)) * (u[j:] @ u[:-j]) / n
    return float(np.sqrt(lrv / n))


def in_sample(d: pd.DataFrame, controls: list[str], interaction: bool = False) -> dict:
    """Full-sample OLS of the full model with full-sample cut-offs (deviation D3)."""
    dd = models.clip(d, models.cutoffs(d))
    months = models._months_in(dd)
    X = models.design(dd, controls, True, months)
    if interaction:
        crisis = dd["winter"].isin(models.CRISIS_WINTERS).to_numpy(float)
        X = np.column_stack([X, crisis, crisis * dd["x"].to_numpy(float)])
    y = dd["y"].to_numpy(float)
    beta = models.ols(X, y)
    resid = y - X @ beta
    k = X.shape[1] - (3 if interaction else 1)  # column of x
    out = {"n": int(len(y)), "winters": int(dd["winter"].nunique())}
    for lag in (NW_LAG, NW_LAG_ROBUST):
        cov = nw_cov(X, resid, lag)
        se = float(np.sqrt(cov[k, k]))
        out[f"se_nw{lag}"] = se
        out[f"p_nw{lag}"] = float(2 * stats.norm.sf(abs(beta[k] / se)))
    out["slope"] = float(beta[k])
    se = out[f"se_nw{NW_LAG}"]
    out["ci95"] = [float(beta[k] - 1.96 * se), float(beta[k] + 1.96 * se)]
    out["per10"] = 10 * out["slope"]
    out["per10_ci95"] = [10 * v for v in out["ci95"]]
    # TOST at 5% against +/- 0.2 EUR/MWh per point.
    p_lo = stats.norm.sf((beta[k] + EQUIV_PER_POINT) / se)
    p_hi = stats.norm.cdf((beta[k] - EQUIV_PER_POINT) / se)
    out["tost_p_lower"], out["tost_p_upper"] = float(p_lo), float(p_hi)
    out["tost_p"] = float(max(p_lo, p_hi))
    # Smallest effect detectable at 5% two-sided with 80% power.
    out["mde_per10"] = float(10 * (stats.norm.ppf(0.975) + stats.norm.ppf(0.8)) * se)
    if interaction:
        cov = nw_cov(X, resid, NW_LAG)
        b_i, se_i = float(beta[-1]), float(np.sqrt(cov[-1, -1]))
        out["interaction"] = b_i
        out["interaction_se_nw4"] = se_i
        out["interaction_p_nw4"] = float(2 * stats.norm.sf(abs(b_i / se_i)))
        out["slope_crisis"] = float(beta[k] + b_i)
    return out


def oos_r2(e_model: np.ndarray, e_bench: np.ndarray) -> float:
    return float(1 - (e_model**2).sum() / (e_bench**2).sum())


def clark_west(y, f_full, f_b3) -> dict:
    """One-sided Clark-West, nested full model against B3, NW lag 4 variance (D5)."""
    e1, e2 = y - f_b3, y - f_full
    f = e1**2 - (e2**2 - (f_b3 - f_full) ** 2)
    t = float(f.mean() / nw_mean_se(f, NW_LAG))
    return {"stat": t, "p_one_sided": float(stats.norm.sf(t))}


def dm_hln(y, f_full, f_bench, h: int = HLN_H) -> dict:
    """Diebold-Mariano with the Harvey-Leybourne-Newbold correction (two-sided)."""
    d = (y - f_full) ** 2 - (y - f_bench) ** 2
    n = len(d)
    u = d - d.mean()
    lrv = u @ u / n + 2 * sum((u[j:] @ u[:-j]) / n for j in range(1, h))
    dm = d.mean() / np.sqrt(lrv / n)
    k = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    stat = float(k * dm)
    return {"stat": stat, "p_two_sided": float(2 * stats.t.sf(abs(stat), df=n - 1))}


def per_winter_beats(o: pd.DataFrame, ycol: str) -> dict:
    out = {}
    for w, g in o.groupby("winter"):
        mf = float(((g[ycol] - g["full"]) ** 2).mean())
        mb = float(((g[ycol] - g["b3"]) ** 2).mean())
        out[int(w)] = {"mse_full": mf, "mse_b3": mb, "full_beats_b3": mf < mb}
    return out


def oos_block(o: pd.DataFrame, ycol: str) -> dict:
    y = o[ycol].to_numpy(float)
    f = {k: o[k].to_numpy(float) for k in ("full", "b0", "b1", "b2", "b3")}
    e = {k: y - v for k, v in f.items()}
    beats = per_winter_beats(o, ycol)
    return {
        "n": int(len(y)),
        "oos_r2": {b: oos_r2(e["full"], e[b]) for b in ("b0", "b1", "b2", "b3")},
        "clark_west_vs_b3": clark_west(y, f["full"], f["b3"]),
        "dm_hln": {b: dm_hln(y, f["full"], f[b]) for b in ("b0", "b1", "b2")},
        "per_winter": beats,
        "winters_full_beats_b3": int(sum(v["full_beats_b3"] for v in beats.values())),
    }


# ---------------------------------------------------------------- bootstrap


def bootstrap(d: pd.DataFrame, o: pd.DataFrame, controls: list[str]) -> dict:
    """Whole-winter resamples (D7): the full-sample slope and the OOS R2 against B3."""
    rng = np.random.default_rng(SEED)
    winters = sorted(d["winter"].unique())
    slopes = []
    for _ in range(N_BOOT):
        pick = rng.choice(winters, size=len(winters), replace=True)
        bd = pd.concat([d[d["winter"] == w] for w in pick], ignore_index=True)
        bd = models.clip(bd, models.cutoffs(bd))
        months = models._months_in(bd)
        X = models.design(bd, controls, True, months)
        slopes.append(models.ols(X, bd["y"].to_numpy(float))[-1])
    tw = sorted(o["winter"].unique())
    r2 = []
    for _ in range(N_BOOT):
        pick = rng.choice(tw, size=len(tw), replace=True)
        bo = pd.concat([o[o["winter"] == w] for w in pick], ignore_index=True)
        r2.append(oos_r2((bo["y"] - bo["full"]).to_numpy(), (bo["y"] - bo["b3"]).to_numpy()))
    s, r = np.array(slopes), np.array(r2)
    return {
        "n_boot": N_BOOT,
        "seed": SEED,
        "slope_ci95": [float(np.quantile(s, 0.025)), float(np.quantile(s, 0.975))],
        "slope_per10_ci95": [float(10 * np.quantile(s, 0.025)), float(10 * np.quantile(s, 0.975))],
        "oos_r2_b3_ci95": [float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))],
        "distinct_test_resamples": 126,  # multisets of 5 winters drawn from 5
    }


# ---------------------------------------------------------------- the variants and verdict


def variant(d: pd.DataFrame, controls: list[str], test_winters: list[int]) -> dict:
    o = models.walk_forward(d, controls, test_winters)
    return {
        "in_sample": in_sample(d, controls),
        "oos_primary_clipped_y": oos_block(o, "y"),
        "oos_robust_raw_y": oos_block(o, "y_raw"),
        "test_winters": test_winters,
        "_oos": o,
    }


def verdict(full: dict, excl: dict) -> dict:
    """Section 5 of the pre-registration, applied mechanically."""
    oo = full["oos_primary_clipped_y"]
    cw_p = oo["clark_west_vs_b3"]["p_one_sided"]
    r2_b3 = oo["oos_r2"]["b3"]
    lo, hi = full["in_sample"]["ci95"]
    ex = excl["oos_primary_clipped_y"]
    sign_flip = np.sign(excl["in_sample"]["slope"]) != np.sign(full["in_sample"]["slope"])
    lines = {
        "1": {
            "text": "Clark-West p is 0.05 or higher, or the out-of-sample R2 against B3 is zero "
            "or below",
            "values": f"CW p = {cw_p:.3f}, OOS R2 vs B3 = {r2_b3:.3f}",
            "holds": bool(cw_p >= 0.05 or r2_b3 <= 0),
        },
        "2": {
            "text": "The 95% interval of the slope sits entirely inside +/- EUR 0.2/MWh per point",
            "values": f"95% interval [{lo:.3f}, {hi:.3f}] per point",
            "holds": bool(lo > -EQUIV_PER_POINT and hi < EQUIV_PER_POINT),
        },
        "3": {
            "text": "The effect disappears without the crisis winters (OOS R2 vs B3 <= 0, or the "
            "slope sign flips, or the full model beats B3 in fewer than 2 of 3 winters), or the "
            "full model beats B3 in fewer than 3 of the 5 test winters",
            "values": (
                f"crisis-excluded OOS R2 vs B3 = {ex['oos_r2']['b3']:.3f}, sign flip = "
                f"{bool(sign_flip)}, beats {ex['winters_full_beats_b3']} of 3; full sample "
                f"beats {oo['winters_full_beats_b3']} of 5"
            ),
            "holds": bool(
                ex["oos_r2"]["b3"] <= 0
                or sign_flip
                or ex["winters_full_beats_b3"] < 2
                or oo["winters_full_beats_b3"] < 3
            ),
        },
    }
    if lines["2"]["holds"]:
        label, deciding = "no effect (equivalence)", ["2"]
    elif lines["1"]["holds"] or lines["3"]["holds"]:
        label = "no edge"
        deciding = [k for k in ("1", "3") if lines[k]["holds"]]
    else:
        label, deciding = "edge", []
    return {"verdict": label, "deciding_lines": deciding, "lines": lines}


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def run(write: bool = True) -> dict:
    import json

    from alpinehydro import features

    f, fr = features.load(), features.load(realised=True)
    pc, rc = models.PRIMARY_CONTROLS, models.REALISED_CONTROLS
    d = models.prepare(f, pc)
    full = variant(d, pc, models.TEST_WINTERS)
    full["bootstrap"] = bootstrap(d, full["_oos"], pc)
    dx = d[~d["winter"].isin(models.CRISIS_WINTERS)].reset_index(drop=True)
    excl = variant(dx, pc, [2023, 2024, 2025])
    inter = in_sample(d, pc, interaction=True)
    dr = models.prepare(fr, rc)
    real = variant(dr, rc, models.TEST_WINTERS)
    h2d = models.prepare(f[f["month"].isin([3, 4])], pc, target="y_it")
    h2 = variant(h2d, pc, models.TEST_WINTERS)
    h2_p = h2["oos_primary_clipped_y"]["clark_west_vs_b3"]["p_one_sided"]
    res = {
        "h1_full_sample": full,
        "h1_crisis_excluded": excl,
        "h1_crisis_interaction": inter,
        "h1_realised_controls": real,
        "verdict": verdict(full, excl),
        "h2": h2,
        "holm": {
            "family": "H2 only so far; recomputed when H3b and N1 are added",
            "adjusted_p": holm({"H2": h2_p}),
        },
        "sample": {
            "origins_total": int(len(f)),
            "origins_used": int(len(d)),
            "winters": sorted(int(w) for w in d["winter"].unique()),
        },
    }
    oos = {k: res[k].pop("_oos") for k in ("h1_full_sample", "h1_crisis_excluded")}
    oos["h1_realised_controls"] = res["h1_realised_controls"].pop("_oos")
    oos["h2"] = res["h2"].pop("_oos")
    if write:
        OUT.write_bytes((json.dumps(res, indent=1, default=float) + "\n").encode("utf-8"))
        for k, v in oos.items():  # forecasts and realised spreads: local only
            v.to_parquet(config.INTERIM / f"oos_{k}.parquet")
    return res
