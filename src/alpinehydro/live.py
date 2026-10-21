"""Live check, winter 2026/27 (pre-registration section 9): one forecast per new origin.

- Model: the full H1 model (and B3, for comparison) trained on every origin of the winters
  2015/16 to 2025/26, with cut-offs from that training set.
- Origin: the latest SFOE week in the merged table (sfoe_storage_merged.csv: CSV where it
  has the week, weekly PDF for newer weeks), if its valid Sunday falls in November to April
  and it has no forecast yet. known_time is the time the week was first seen: the PDF log
  for a PDF week, the CSV release log for a CSV week. The target window starts after it.
- Output: data/processed/live_forecasts.csv (committed: forecasts and inputs only). The
  realised mean spread, one derived number per window, is added later in realised_spread.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from alpinehydro import config, features, models

OUT = config.PROCESSED / "live_forecasts.csv"
TZ = "Europe/Zurich"
COLUMNS = [
    "valid_sunday",
    "known_time",
    "known_time_source",
    "origin_day",
    "target_start",
    "target_end",
    "dev_10y_pp",
    *models.PRIMARY_CONTROLS,
    "forecast_full",
    "forecast_b3",
    "made_at_utc",
    "model",
    "realised_spread",
]


def train() -> dict:
    """Full model and B3 on all winters to 2025/26, training cut-offs."""
    d = models.prepare(features.load(), models.PRIMARY_CONTROLS)
    d = d[d["winter"] <= 2025]
    cut = models.cutoffs(d)
    tr = models.clip(d, cut)
    months = models._months_in(tr)
    pc = models.PRIMARY_CONTROLS
    return {
        "full": models.ols(models.design(tr, pc, True, months), tr["y"].to_numpy()),
        "b3": models.ols(models.design(tr, pc, False, months), tr["y"].to_numpy()),
        "cut": cut,
        "months": months,
        "label": f"full H1 model, OLS on {len(tr)} origins, winters 2015/16 to 2025/26",
    }


def latest_week() -> dict:
    """Latest week of the merged table, its source and its first-seen time."""
    from alpinehydro.fetch import sfoe_pdf

    s = sfoe_pdf.load_merged()
    total = s[s["region"] == "TotalCH"].sort_values("valid_time")
    row = total.iloc[-1]
    last = row["valid_time"]
    if row["source"] == "pdf":
        seen = row["known_time"].tz_convert("UTC")
        src = "SFOE weekly PDF, first seen in sfoe_pdf_log.csv"
    else:
        rel = pd.read_csv(config.PROCESSED / "sfoe_release_log.csv", parse_dates=["valid_sunday"])
        hit = rel.loc[rel["valid_sunday"] == last, "first_seen_utc"]
        seen = pd.Timestamp(hit.iloc[0]) if len(hit) else None
        src = "SFOE CSV, first seen in sfoe_release_log.csv"
    return {"valid_sunday": last, "first_seen_utc": seen, "source": src, "storage": s}


def next_possible(after: pd.Timestamp) -> pd.Timestamp:
    """First Sunday in November to April after the given Sunday."""
    d = after + pd.Timedelta(days=7)
    while d.month not in features.SEASON_MONTHS:
        d += pd.Timedelta(days=7)
    return d


def forecast(write: bool = True) -> dict:
    from alpinehydro.norms import add_norms

    w = latest_week()
    vs = w["valid_sunday"]
    status = {"latest_week": str(vs.date()), "latest_week_source": w["source"]}
    if vs.month not in features.SEASON_MONTHS:
        first = next_possible(vs)
        status["made"] = False
        status["reason"] = (
            f"latest SFOE week {vs.date()} is outside November to April; the first live origin "
            f"is the week of Sunday {first.date()}, made as soon as SFOE releases it (PDF or CSV)"
        )
        return status
    if w["first_seen_utc"] is None:
        status["made"] = False
        status["reason"] = f"week {vs.date()} has no first-seen time in the release logs"
        return status
    done = pd.read_csv(OUT, comment="#") if OUT.exists() else pd.DataFrame(columns=COLUMNS)
    if str(vs.date()) in set(done["valid_sunday"].astype(str)):
        status["made"] = False
        status["reason"] = "this origin already has a forecast"
        return status
    kt = w["first_seen_utc"].tz_convert(TZ)
    d = add_norms(w["storage"].query("region == 'TotalCH'"), windows=(10,))
    x = float(d.loc[d["valid_time"] == vs, "dev_10y_pp"].iloc[0])
    od = kt.tz_localize(None).normalize()
    start = features.target_start(kt)
    r = pd.DataFrame(
        [
            {
                "valid_time": vs,
                "known_time": kt,
                "origin_day": od,
                "target_start": start,
                "target_end": start + pd.Timedelta(days=features.WINDOW_DAYS - 1),
                "winter": vs.year - int(vs.month <= 4),
                "month": vs.month,
                "dev_10y_pp": x,
            }
        ]
    )
    spread = features.daily_spread("CH", "DE_LU")
    spread_it = features.daily_spread("CH", "IT_NORD")
    row, _ = features.origin_features(
        next(r.itertuples()), spread, spread_it, features.daily_controls()
    )
    missing = [k for k in models.PRIMARY_CONTROLS if not np.isfinite(row[k])]
    if missing:
        status["made"] = False
        status["reason"] = f"controls below the 90% coverage floor: {missing}"
        return status
    m = train()
    one = models.clip(
        pd.DataFrame([row]).rename(columns={"dev_10y_pp": "x"}).assign(y=0.0), m["cut"]
    )
    pc = models.PRIMARY_CONTROLS
    out = {
        "valid_sunday": str(vs.date()),
        "known_time": kt.isoformat(),
        "known_time_source": w["source"],
        "origin_day": str(od.date()),
        "target_start": str(start.date()),
        "target_end": str(row["target_end"].date()),
        "dev_10y_pp": round(x, 3),
        **{k: round(float(row[k]), 3) for k in pc},
        "forecast_full": round(
            float((models.design(one, pc, True, m["months"]) @ m["full"])[0]), 2
        ),
        "forecast_b3": round(float((models.design(one, pc, False, m["months"]) @ m["b3"])[0]), 2),
        "made_at_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": m["label"],
        "realised_spread": "",
    }
    if write:
        table = pd.concat([done, pd.DataFrame([out])], ignore_index=True)[COLUMNS]
        header = [
            "# Live H1 forecasts, winter 2026/27 (pre-registration section 9). Forecasts and",
            "# their inputs only; realised_spread will hold one derived number per window (the",
            "# mean CH minus DE-LU baseload spread), never a price series.",
        ]
        text = "\n".join(header) + "\n" + table.to_csv(index=False, lineterminator="\n")
        OUT.write_bytes(text.encode("utf-8"))
    status["made"] = True
    status["forecast"] = out
    return status
