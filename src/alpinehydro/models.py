"""H1 benchmarks, full model and the walk-forward design, as pre-registered.

- B0: training-mean y for the origin month (the valid Sunday's month, deviation D1).
- B1: the mean spread over the 28 delivery days ending the day before the origin day (D6).
- B2: B1 plus the training-mean change (y minus last28) for the same month.
- B3: OLS of y on the controls and month dummies (November is the base).
- Full: B3 plus dev_10y_pp.

Walk-forward: folds are hydrological years, expanding window, re-estimated each 1 October.
Training rows are origins of earlier winters whose target ends at least 28 days before the
first test origin (the 4-week gap). A winter is tested only with at least 6 training
winters. Winsorisation of x and y at the 1st and 99th percentile uses training cut-offs
only; test x and test y are clipped at those cut-offs for the primary scoring (D2), and the
raw test y is kept for the robustness scoring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRIMARY_CONTROLS = [
    "fr_nuclear",
    "de_wind",
    "ch_nuclear",
    "hdd_ch",
    "hdd_de",
    "clim_hdd_ch",
    "clim_hdd_de",
]
REALISED_CONTROLS = ["fr_nuclear", "de_wind", "ch_nuclear", "hdd_ch", "hdd_de"]
MONTHS = [12, 1, 2, 3, 4]  # dummies; November is the base
FIRST_WINTER = 2015  # first full winter with prices (2015/16)
TEST_WINTERS = [2021, 2022, 2023, 2024, 2025]
MIN_TRAIN_WINTERS = 6
GAP_DAYS = 28
WINSOR = (0.01, 0.99)
CRISIS_WINTERS = [2021, 2022]


def design(df: pd.DataFrame, controls: list[str], with_x: bool, months=MONTHS) -> np.ndarray:
    cols = [np.ones(len(df))] + [df[c].to_numpy(float) for c in controls]
    cols += [(df["month"] == m).to_numpy(float) for m in months]
    if with_x:
        cols.append(df["x"].to_numpy(float))
    return np.column_stack(cols)


def _months_in(train: pd.DataFrame) -> list[int]:
    """Dummies only for months present in training (H2 uses March and April only)."""
    present = sorted(set(train["month"]))
    base = 11 if 11 in present else present[0]
    return [m for m in MONTHS + [11] if m in present and m != base]


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cutoffs(train: pd.DataFrame) -> dict[str, tuple[float, float]]:
    return {c: tuple(np.quantile(train[c], WINSOR)) for c in ("x", "y")}


def clip(df: pd.DataFrame, cut: dict) -> pd.DataFrame:
    out = df.copy()
    for c, (lo, hi) in cut.items():
        out[c] = out[c].clip(lo, hi)
    return out


def prepare(f: pd.DataFrame, controls: list[str], target: str = "y") -> pd.DataFrame:
    """Rows with a complete target window and every control; x and y named generically."""
    d = f.rename(columns={"dev_10y_pp": "x"}).copy()
    d["y"] = d[target]
    d["y_raw"] = d[target]
    days = d[f"{target}_days"] if f"{target}_days" in d else d["y_days"]
    keep = (d["winter"] >= FIRST_WINTER) & (days == 28)
    keep &= d[["x", "y", "last28"]].notna().all(axis=1)
    # Deviation D9: a control below 90% coverage is missing and drops the origin.
    has_controls = d[controls].notna().all(axis=1)
    out = d[keep & has_controls].reset_index(drop=True)
    out.attrs["dropped_for_coverage"] = int((keep & ~has_controls).sum())
    return out


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, controls: list[str]) -> pd.DataFrame:
    """Fit every model on (winsorised) training rows and forecast the test rows."""
    cut = cutoffs(train)
    tr, te = clip(train, cut), clip(test, cut)
    months = _months_in(tr)
    out = te[["valid_time", "origin_day", "winter", "month", "x", "y", "y_raw"]].copy()
    m_mean = tr.groupby("month")["y"].mean()
    out["b0"] = te["month"].map(m_mean).to_numpy()
    out["b1"] = te["last28"].to_numpy()
    chg = (tr["y"] - tr["last28"]).groupby(tr["month"]).mean()
    out["b2"] = (te["last28"] + te["month"].map(chg)).to_numpy()
    b3 = ols(design(tr, controls, False, months), tr["y"].to_numpy())
    out["b3"] = design(te, controls, False, months) @ b3
    full = ols(design(tr, controls, True, months), tr["y"].to_numpy())
    out["full"] = design(te, controls, True, months) @ full
    out["slope"] = full[-1]
    out["n_train"] = len(tr)
    out["train_winters"] = tr["winter"].nunique()
    out["cut_y_lo"], out["cut_y_hi"] = cut["y"]
    return out


def walk_forward(
    d: pd.DataFrame, controls: list[str], test_winters: list[int] = TEST_WINTERS
) -> pd.DataFrame:
    parts = []
    for w in test_winters:
        test = d[d["winter"] == w]
        if test.empty:
            continue
        first = test["origin_day"].min()
        train = d[(d["winter"] < w) & (d["target_end"] <= first - pd.Timedelta(days=GAP_DAYS))]
        if train["winter"].nunique() < MIN_TRAIN_WINTERS:
            raise ValueError(f"winter {w}: only {train['winter'].nunique()} training winters")
        parts.append(fit_predict(train, test, controls))
    return pd.concat(parts, ignore_index=True)
