"""Independent level check against DAHITI satellite altimetry (private check only).

DAHITI (Database for Hydrological Time Series of Inland Waters, DGFI-TUM) is free for
noncommercial use with a personal API key in DAHITI_API_KEY. Its raw data stay in
data/raw/dahiti/ (git-ignored). Nothing from DAHITI is committed or shown in the README;
only summary numbers go into the private vault note.

DAHITI heights are orthometric heights on a global geoid; our levels are Swiss heights
(LN02, via swissALTI3D). The two datums differ by a near-constant offset, so the mean
difference mixes datum and bias. The RMSE after removing the mean is the fair number.

Credit: Schwatke, C., Dettmering, D., Bosch, W., Seitz, F. (2015). DAHITI, an innovative
approach for estimating water level time series over inland waters using multi-mission
satellite altimetry. Hydrol. Earth Syst. Sci., 19, 4345-4364. Data: dahiti.dgfi.tum.de.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from alpinehydro import config, outlines

API = "https://dahiti.dgfi.tum.de/api/v2/"
RAW_DIR = config.RAW / "dahiti"


def _post(endpoint: str, **params) -> dict:
    import requests

    params["api_key"] = config.secret("DAHITI_API_KEY")
    r = requests.post(API + endpoint + "/", json=params, timeout=60)
    r.raise_for_status()
    out = r.json()
    if out.get("code") != 200:
        raise RuntimeError(f"DAHITI {endpoint}: {out.get('code')} {out.get('message')}")
    return out


def find_target(slug: str, pad_deg: float = 0.05) -> dict:
    """The DAHITI target whose point lies closest to the lake, within a small box."""
    lake = outlines.transform(outlines.to_wgs84, outlines.load(slug, "outline"))
    x0, y0, x1, y1 = lake.bounds
    out = _post(
        "list-targets",
        min_lon=x0 - pad_deg,
        max_lon=x1 + pad_deg,
        min_lat=y0 - pad_deg,
        max_lat=y1 + pad_deg,
    )
    targets = [t for t in out["data"] if (t.get("data_access") or {}).get("water_level_altimetry")]
    if not targets:
        raise RuntimeError(f"no DAHITI water-level target near {slug}")
    c = lake.centroid
    return min(targets, key=lambda t: np.hypot(t["longitude"] - c.x, t["latitude"] - c.y))


def fetch(slug: str, refresh: bool = False) -> pd.DataFrame:
    """DAHITI water levels for the lake: date, wse, wse_u (cached raw JSON)."""
    path = RAW_DIR / f"{slug}.json"
    if refresh or not path.exists():
        target = find_target(slug)
        out = _post("download-water-level", dahiti_id=target["dahiti_id"], format="json")
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out), encoding="utf-8")
    out = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(out["data"])
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "wse", "wse_u"]].sort_values("date").reset_index(drop=True)


def compare(scenes: pd.DataFrame, levels: pd.DataFrame, max_days: float = 3.0) -> dict:
    """Pair each ok scene with the closest DAHITI level within max_days.

    Returns n, mean difference (ours minus DAHITI), RMSE, and RMSE after removing the mean.
    """
    ok = scenes[scenes["flag"] == "ok"].copy()
    ok["t"] = pd.to_datetime(ok["time_utc"], utc=True).dt.tz_localize(None)
    lv = levels.sort_values("date")
    pairs = pd.merge_asof(
        ok.sort_values("t"),
        lv.rename(columns={"date": "t_dahiti"}),
        left_on="t",
        right_on="t_dahiti",
        direction="nearest",
        tolerance=pd.Timedelta(days=max_days),
    ).dropna(subset=["wse"])
    d = pairs["level_m"] - pairs["wse"]
    n = len(d)
    return {
        "n": n,
        "mean_difference_m": round(float(d.mean()), 3) if n else None,
        "rmse_m": round(float(np.sqrt((d**2).mean())), 3) if n else None,
        "rmse_after_mean_m": round(float(d.std(ddof=0)), 3) if n else None,
        "dahiti_points": len(lv),
        "first": str(lv["date"].min().date()) if len(lv) else None,
        "last": str(lv["date"].max().date()) if len(lv) else None,
    }
