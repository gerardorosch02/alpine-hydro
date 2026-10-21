"""Validation of the satellite Wallis series against SFOE Wallis (Part A's own target).

- Satellite Wallis = the sum of the energy (GWh) of Dix, Emosson and Mauvoisin. A week is
  ok only if all three lakes have an ok scene within 3 days of the week end.
- Calibration: only a scale and an offset, SFOE Wallis GWh = a + b x satellite GWh, fitted
  walk-forward by hydrological year (1 October to 30 September) on ok weeks of earlier
  years. The first year is fitted on itself, reported as in-sample and left out of the
  metrics.
- Anomaly: the deviation from the mean of the same ISO week across the other scored years,
  for both series, in percentage points of SFOE Wallis capacity (max_gwh that week).
- Metrics on June to November ok weeks: R2 = 1 - SSE / SST of the SFOE anomalies, mean
  absolute error, bias (satellite minus SFOE), n, and a breakdown by month.
- Pass if R2 >= 0.5, i.e. the satellite explains at least half the variance of the SFOE
  Wallis anomalies on clear weeks. This is not part of the price pre-registration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alpinehydro import config, weekly

WALLIS = ["dix", "emosson", "mauvoisin"]
PASS_R2 = 0.5
OUT = config.PROCESSED / "satellite" / "wallis.csv"


def hydro_year(t: pd.Series) -> pd.Series:
    """Hydrological year by its start: October 2020 to September 2021 is 2020."""
    t = pd.to_datetime(t)
    return t.dt.year - (t.dt.month < 10).astype(int)


def wallis_series(wk: pd.DataFrame, storage: pd.DataFrame, lakes: list[str]) -> pd.DataFrame:
    """Weekly sum over lakes with SFOE Wallis beside it. status ok only if every lake is ok."""
    w = wk[wk["reservoir"].isin(lakes)]
    g = w.groupby("valid_time")
    df = pd.DataFrame(
        {
            "sat_gwh": g["energy_gwh"].sum(),
            "n_lakes": g["reservoir"].nunique(),
            "n_ok": g["status"].apply(lambda s: int((s == "ok").sum())),
        }
    ).reset_index()
    df = df[df["n_lakes"] == len(lakes)].copy()
    df["ok"] = df["n_ok"] == len(lakes)
    sf = storage[storage["region"] == "Wallis"][["valid_time", "content_gwh", "max_gwh"]]
    df = df.merge(sf, on="valid_time", how="inner")
    df["hydro_year"] = hydro_year(df["valid_time"])
    df["month"] = df["valid_time"].dt.month
    df["iso_week"] = df["valid_time"].dt.isocalendar().week.astype(int)
    return df.sort_values("valid_time").reset_index(drop=True)


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """Add sat_cal_gwh: scale and offset fitted on ok weeks of earlier hydrological years."""
    df = df.copy()
    df["sat_cal_gwh"] = np.nan
    df["in_sample"] = False
    years = sorted(df.loc[df["ok"], "hydro_year"].unique())
    for i, y in enumerate(years):
        train = df[df["ok"] & (df["hydro_year"] < y)]
        if i == 0:
            train = df[df["ok"] & (df["hydro_year"] == y)]
            df.loc[df["hydro_year"] == y, "in_sample"] = True
        if len(train) < 2:
            continue
        b, a = np.polyfit(train["sat_gwh"], train["content_gwh"], 1)
        rows = df["hydro_year"] == y
        df.loc[rows, "sat_cal_gwh"] = a + b * df.loc[rows, "sat_gwh"]
        df.loc[rows, "fit_a"] = a
        df.loc[rows, "fit_b"] = b
        df.loc[rows, "fit_n"] = len(train)
    df["sat_fill_pp"] = 100 * df["sat_cal_gwh"] / df["max_gwh"]
    df["sfoe_fill_pp"] = 100 * df["content_gwh"] / df["max_gwh"]
    return df


def anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Scored weeks (June to November, ok, out of sample) with leave-one-year-out anomalies."""
    s = df[df["ok"] & ~df["in_sample"] & df["month"].between(6, 11)]
    s = s.dropna(subset=["sat_fill_pp"]).copy()
    for col in ("sat_fill_pp", "sfoe_fill_pp"):
        tot = s.groupby("iso_week")[col].transform("sum")
        cnt = s.groupby("iso_week")[col].transform("count")
        s[col.replace("_fill_pp", "_anom_pp")] = s[col] - (tot - s[col]) / (cnt - 1)
    # A week with no other year has no climatology.
    return s[s.groupby("iso_week")["sat_fill_pp"].transform("count") > 1].copy()


def metrics(s: pd.DataFrame) -> dict:
    if len(s) < 2:
        return {"n": len(s)}
    e = s["sat_anom_pp"] - s["sfoe_anom_pp"]
    sst = float(((s["sfoe_anom_pp"] - s["sfoe_anom_pp"].mean()) ** 2).sum())
    r2 = 1 - float((e**2).sum()) / sst if sst > 0 else float("nan")
    return {
        "n": int(len(s)),
        "r2": round(r2, 3),
        "corr2": round(float(np.corrcoef(s["sat_anom_pp"], s["sfoe_anom_pp"])[0, 1] ** 2), 3),
        "mae_pp": round(float(e.abs().mean()), 2),
        # Leave-one-year-out anomalies sum to zero within each week, so their bias is ~0 by
        # construction; the bias and error of the calibrated fill itself are reported too.
        "bias_pp": round(float(e.mean()), 2),
        "fill_bias_pp": round(float((s["sat_fill_pp"] - s["sfoe_fill_pp"]).mean()), 2),
        "fill_mae_pp": round(float((s["sat_fill_pp"] - s["sfoe_fill_pp"]).abs().mean()), 2),
        "sd_sfoe_anom_pp": round(float(s["sfoe_anom_pp"].std(ddof=0)), 2),
        "years": f"{int(s['hydro_year'].min())}/{int(s['hydro_year'].min()) + 1} to "
        f"{int(s['hydro_year'].max())}/{int(s['hydro_year'].max()) + 1}",
    }


def run(lakes: list[str] | None = None, write: bool = False) -> dict:
    from alpinehydro.fetch import sfoe

    lakes = lakes or WALLIS
    df = walk_forward(wallis_series(weekly.load(), sfoe.load_processed(), lakes))
    s = anomalies(df)
    m = metrics(s)
    m["pass"] = bool(m.get("r2", -np.inf) >= PASS_R2)
    m["lakes"] = lakes
    m["in_sample_year"] = int(df.loc[df["in_sample"], "hydro_year"].min())
    m["weeks_all_three_seen"] = int(len(df))
    m["weeks_ok"] = int(df["ok"].sum())
    m["by_month"] = {int(k): metrics(g) for k, g in s.groupby("month")}
    if write:
        cols = ["valid_time", "hydro_year", "sat_gwh", "n_ok", "ok", "in_sample", "sat_cal_gwh"]
        cols += ["content_gwh", "max_gwh", "sat_fill_pp", "sfoe_fill_pp"]
        out = df[cols].merge(
            s[["valid_time", "sat_anom_pp", "sfoe_anom_pp"]], on="valid_time", how="left"
        )
        header = [
            "# Satellite Wallis (Dix + Emosson + Mauvoisin) against SFOE Wallis, walk-forward",
            "# calibrated by hydrological year. Anomalies only on scored weeks (June to November,",
            "# ok, out of sample). Source: Swiss Federal Office of Energy SFOE. Contains modified",
            "# Copernicus Sentinel data. Landsat courtesy of the U.S. Geological Survey. Source:",
            "# Federal Office of Topography swisstopo.",
        ]
        text = (
            "\n".join(header)
            + "\n"
            + out.round({c: 3 for c in cols[2:] + ["sat_anom_pp", "sfoe_anom_pp"]}).to_csv(
                index=False, lineterminator="\n"
            )
        )
        OUT.write_bytes(text.encode("utf-8"))
    return m
