"""H3a and H3b tests and the Holm update, exactly as `prereg/H3_ANALYSIS_PLAN.md`.

H3a: end-of-September fill = a + b × snow + c × starting storage, against C0 (10-year
climatology) and C1 (starting storage only). Walk-forward (expanding, test years 2011 to
2026, sample from 2001) is primary; leave-one-year-out (2001 to 2026) is secondary.
H3b: the October to December spread regressed on the walk-forward 1 May forecast of the
total end-of-season fill deviation from its 10-year norm, 2015 to 2025.
Output: reports/checks/h3_results.json (statistics only, no price series).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from alpinehydro import config, features_snow

OUT = config.ROOT / "reports" / "checks" / "h3_results.json"
H1_RESULTS = config.ROOT / "reports" / "checks" / "h1_results.json"
FIRST_YEAR = 2001
TEST_YEARS = list(range(2011, 2027))
H3B_MIN_TRAIN = 5
PRIMARY = {
    "region": "Total",
    "source": "modis",
    "issue": "may1",
    "band_m": 1800,
    "target": "end_fill_pp",
}
SNOW_COL = {"modis": "modis_fsc", "era5": "era5_swe", "era5_anom10": "era5_anom10"}
C0_COL = {"end_fill_pp": "c0_fill_pp", "refill_gwh": "c0_refill_gwh"}


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def _X(d: pd.DataFrame, cols: list[str]) -> np.ndarray:
    return np.column_stack([np.ones(len(d)), *[d[c].to_numpy(float) for c in cols]])


def predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str], target: str) -> np.ndarray:
    b = ols(_X(train, cols), train[target].to_numpy(float))
    return _X(test, cols) @ b


def version_table(
    f: pd.DataFrame, region: str, issue: str, band: int, source: str, target: str
) -> pd.DataFrame:
    snow_col = SNOW_COL[source]
    d = f[(f["region"] == region) & (f["issue"] == issue) & (f["band_m"] == band)]
    d = d[(d["year"] >= FIRST_YEAR)].copy()
    d["snow"] = d[snow_col]
    d["y"] = d[target]
    d["c0"] = d[C0_COL[target]]
    return d.sort_values("year").reset_index(drop=True)


def walk_forward(d: pd.DataFrame) -> pd.DataFrame:
    """Expanding window: test year Y is fitted on every complete sample year before Y."""
    ok = d.dropna(subset=["snow", "start_fill_pp", "y"])
    rows = []
    for y in TEST_YEARS:
        test = ok[ok["year"] == y]
        train = ok[ok["year"] < y]
        if test.empty or len(train) < 10:
            continue
        rows.append(
            {
                "year": y,
                "y": float(test["y"].iloc[0]),
                "full": float(predict(train, test, ["snow", "start_fill_pp"], "y")[0]),
                "c1": float(predict(train, test, ["start_fill_pp"], "y")[0]),
                "c0": float(test["c0"].iloc[0]),
                "n_train": len(train),
                "train_first": int(train["year"].min()),
                "train_last": int(train["year"].max()),
            }
        )
    return pd.DataFrame(rows)


def loyo(d: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-year-out across the sample years; C0 is the mean of the other years."""
    ok = d.dropna(subset=["snow", "start_fill_pp", "y"])
    rows = []
    for y in ok["year"]:
        test, train = ok[ok["year"] == y], ok[ok["year"] != y]
        rows.append(
            {
                "year": int(y),
                "y": float(test["y"].iloc[0]),
                "full": float(predict(train, test, ["snow", "start_fill_pp"], "y")[0]),
                "c1": float(predict(train, test, ["start_fill_pp"], "y")[0]),
                "c0": float(train["y"].mean()),
            }
        )
    return pd.DataFrame(rows)


def skill(y, f, b) -> float:
    return float(1 - np.mean((y - f) ** 2) / np.mean((y - b) ** 2))


def clark_west(y, f_full, f_small) -> dict:
    """One-sided Clark-West, one forecast per year, t with n - 1 df."""
    f = (y - f_small) ** 2 - ((y - f_full) ** 2 - (f_small - f_full) ** 2)
    n = len(f)
    t = float(f.mean() / (f.std(ddof=1) / np.sqrt(n)))
    return {"stat": t, "p_one_sided": float(stats.t.sf(t, df=n - 1)), "n": n}


def dm_hln(y, f_full, f_bench) -> dict:
    """Diebold-Mariano, Harvey-Leybourne-Newbold correction, h = 1, two-sided t(n - 1)."""
    d = (y - f_full) ** 2 - (y - f_bench) ** 2
    n = len(d)
    dm = d.mean() / np.sqrt(((d - d.mean()) @ (d - d.mean()) / n) / n)
    k = np.sqrt((n + 1 - 2 + 0) / n)
    stat = float(k * dm)
    return {"stat": stat, "p_two_sided": float(2 * stats.t.sf(abs(stat), df=n - 1)), "n": n}


def score(o: pd.DataFrame) -> dict:
    y, full, c1 = (o[c].to_numpy(float) for c in ("y", "full", "c1"))
    c0 = o["c0"].to_numpy(float)
    has_c0 = np.isfinite(c0)
    out = {
        "n": len(o),
        "years": [int(o["year"].min()), int(o["year"].max())] if len(o) else None,
        "rmse_full": float(np.sqrt(np.mean((y - full) ** 2))),
        "rmse_c1": float(np.sqrt(np.mean((y - c1) ** 2))),
        "skill_vs_c1": skill(y, full, c1),
        "clark_west_vs_c1": clark_west(y, full, c1),
    }
    if has_c0.all():
        out["rmse_c0"] = float(np.sqrt(np.mean((y - c0) ** 2)))
        out["skill_vs_c0"] = skill(y, full, c0)
        out["dm_hln_vs_c0"] = dm_hln(y, full, c0)
    return out


def in_sample_slope(d: pd.DataFrame) -> dict:
    ok = d.dropna(subset=["snow", "start_fill_pp", "y"])
    X, y = _X(ok, ["snow", "start_fill_pp"]), ok["y"].to_numpy(float)
    b = ols(X, y)
    return {
        "a": float(b[0]),
        "b_snow": float(b[1]),
        "c_start": float(b[2]),
        "n": len(ok),
        "dropped_years": sorted(set(d["year"]) - set(ok["year"])),
    }


def run_version(f: pd.DataFrame, region, issue, band, source, target) -> dict:
    d = version_table(f, region, issue, band, source, target)
    wf, lo = walk_forward(d), loyo(d)
    return {
        "key": {
            "region": region,
            "issue": issue,
            "band_m": band,
            "source": source,
            "target": target,
        },
        "in_sample": in_sample_slope(d),
        "walk_forward": score(wf),
        "loyo": score(lo),
        "wf_rows": wf.round(3).to_dict(orient="records"),
    }


def hc3(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    b = ols(X, y)
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    h = np.einsum("ij,jk,ik->i", X, XtXi, X)
    meat = X.T @ (X * (e / (1 - h))[:, None] ** 2)
    return b, np.sqrt(np.diag(XtXi @ meat @ XtXi))


def h3b(primary_wf: pd.DataFrame, f: pd.DataFrame, q4: pd.DataFrame) -> dict:
    tot = f[(f["region"] == "Total") & (f["issue"] == "may1") & (f["band_m"] == 1800)]
    norm = tot.set_index("year")["norm10_end_pp"]
    d = primary_wf.set_index("year")[["full"]].join(norm).join(q4.set_index("year"))
    d = d.loc[[y for y in features_snow.H3B_YEARS if y in d.index]].dropna(
        subset=["full", "norm10_end_pp", "q4_spread_eur_mwh"]
    )
    d["x"] = d["full"] - d["norm10_end_pp"]
    X, y = np.column_stack([np.ones(len(d)), d["x"]]), d["q4_spread_eur_mwh"].to_numpy(float)
    b, se = hc3(X, y)
    n = len(d)
    tq = stats.t.ppf(0.975, n - 2)
    # Clark-West against intercept-only, expanding window with >= 5 training years.
    rows = []
    years = list(d.index)
    for i, yr in enumerate(years):
        if i < H3B_MIN_TRAIN:
            continue
        tr = d.loc[years[:i]]
        bt = ols(np.column_stack([np.ones(len(tr)), tr["x"]]), tr["q4_spread_eur_mwh"].to_numpy())
        rows.append(
            {
                "year": int(yr),
                "y": float(d.loc[yr, "q4_spread_eur_mwh"]),
                "full": float(bt[0] + bt[1] * d.loc[yr, "x"]),
                "mean": float(tr["q4_spread_eur_mwh"].mean()),
            }
        )
    o = pd.DataFrame(rows)
    cw = clark_west(o["y"].to_numpy(), o["full"].to_numpy(), o["mean"].to_numpy())
    mde = (stats.t.ppf(0.975, n - 2) + stats.t.ppf(0.80, n - 2)) * se[1] * 10
    return {
        "n": n,
        "years": [int(min(years)), int(max(years))],
        "slope_per10": float(b[1] * 10),
        "ci95_per10": [float((b[1] - tq * se[1]) * 10), float((b[1] + tq * se[1]) * 10)],
        "se_hc3_per10": float(se[1] * 10),
        "p_two_sided_hc3": float(2 * stats.t.sf(abs(b[1] / se[1]), n - 2)),
        "clark_west_vs_mean": cw,
        "oos_test_years": [int(o["year"].min()), int(o["year"].max())],
        "oos_skill_vs_mean": skill(o["y"].to_numpy(), o["full"].to_numpy(), o["mean"].to_numpy()),
        "mde_per10": float(mde),
        "x_by_year": d["x"].round(2).to_dict(),
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def run(write: bool = True) -> dict:
    f = features_snow.load()
    q4 = features_snow.load_q4()
    versions = []
    for target in ("end_fill_pp", "refill_gwh"):
        for region in ("Total", "Wallis", "Graubuenden", "Tessin"):
            for issue in ("may1", "apr1"):
                for band in (1800, 2000):
                    for source in ("modis", "era5", "era5_anom10"):
                        versions.append(run_version(f, region, issue, band, source, target))
    prim = next(v for v in versions if v["key"] == PRIMARY)
    wf_prim = pd.DataFrame(prim["wf_rows"])
    h3b_res = h3b(wf_prim, f, q4)
    h2_p = json.loads(H1_RESULTS.read_text())["h2"]["oos_primary_clipped_y"]["clark_west_vs_b3"][
        "p_one_sided"
    ]
    raw = {
        "H2": h2_p,
        "H3a": prim["walk_forward"]["clark_west_vs_c1"]["p_one_sided"],
        "H3b": h3b_res["clark_west_vs_mean"]["p_one_sided"],
    }
    adj = holm(raw)
    passed = prim["walk_forward"]["skill_vs_c1"] > 0 and adj["H3a"] < 0.05
    case = next(r for r in prim["wf_rows"] if r["year"] == 2026)
    res = {
        "plan": "prereg/H3_ANALYSIS_PLAN.md (tag v0.2-h3plan)",
        "primary_key": PRIMARY,
        "verdict": "pass" if passed else "no added skill from snow",
        "primary": prim,
        "h3b": h3b_res,
        "holm": {
            "family": ["H2", "H3a", "H3b"],
            "raw_p": raw,
            "adjusted_p": adj,
            "n1": "not run (Part A closed; timing ceiling about EUR 0.2/MWh)",
        },
        "case_2026": case,
        "versions": versions,
    }
    if write:
        OUT.write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    return res
