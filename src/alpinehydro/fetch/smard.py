"""SMARD day-ahead prices (Bundesnetzagentur), a licence-safe cross-check.

SMARD market data are published under CC BY 4.0 with the credit
"Bundesnetzagentur | SMARD.de" (smard.de/home/datennutzung, checked 2026-10-20).
The raw weekly JSON chunks are cached in data/raw/smard/ and the hourly table
in data/interim/. Nothing price-like is committed this weekend; only the
cross-check statistics go into reports/results.md.
"""

from __future__ import annotations

import json
import time

import pandas as pd
import requests

from alpinehydro import config
from alpinehydro.fetch.entsoe import TZ, to_hourly

CREDIT = "Bundesnetzagentur | SMARD.de"
BASE = "https://www.smard.de/app/chart_data"
REGION = "DE-LU"
RAW_DIR = config.RAW / "smard"
HEADERS = {"User-Agent": "alpinehydro research project"}


def _get_json(url: str) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers=HEADERS)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_filter(filter_id: int, start: str, refresh: bool = False) -> pd.Series:
    """Fetch hourly prices for one SMARD filter, caching each weekly chunk."""
    index = _get_json(f"{BASE}/{filter_id}/{REGION}/index_hour.json")["timestamps"]
    start_ms = pd.Timestamp(start, tz=TZ).value // 10**6 - 7 * 24 * 3600 * 1000
    now_ms = pd.Timestamp.now(tz="UTC").value // 10**6
    out_dir = RAW_DIR / str(filter_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for ts in index:
        if ts < start_ms:
            continue
        path = out_dir / f"{ts}.json"
        final = ts + 9 * 24 * 3600 * 1000 < now_ms
        if path.exists() and final and not refresh:
            series = json.loads(path.read_text(encoding="utf-8"))["series"]
        else:
            series = _get_json(f"{BASE}/{filter_id}/{REGION}/{filter_id}_{REGION}_hour_{ts}.json")[
                "series"
            ]
            path.write_text(json.dumps({"series": series}), encoding="utf-8")
        rows.extend(series)
    s = pd.Series(
        [v for _, v in rows],
        index=pd.to_datetime([t for t, _ in rows], unit="ms", utc=True),
        dtype=float,
    ).dropna()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s[s.index >= pd.Timestamp(start, tz=TZ)]


def fetch_all(refresh: bool = False) -> pd.DataFrame:
    cfg = config.pipeline()["smard"]
    parts = []
    for zone, fid in cfg["filters"].items():
        h = to_hourly(fetch_filter(fid, cfg["start"], refresh=refresh)).reset_index()
        h.insert(0, "zone", zone)
        parts.append(h)
    df = pd.concat(parts, ignore_index=True)
    config.INTERIM.mkdir(parents=True, exist_ok=True)
    df.to_parquet(config.INTERIM / "smard_prices_hourly.parquet")
    return df


def cross_check(smard_hourly: pd.DataFrame, entsoe_hourly: pd.DataFrame) -> dict:
    """Correlation and mean absolute difference per zone over the overlapping hours."""
    out = {}
    for zone in smard_hourly["zone"].unique():
        a = smard_hourly[smard_hourly["zone"] == zone].set_index("hour_start")["price"]
        b = entsoe_hourly[entsoe_hourly["zone"] == zone].set_index("hour_start")["price"]
        j = pd.concat([a.rename("smard"), b.rename("entsoe")], axis=1, join="inner").dropna()
        diff = (j["smard"] - j["entsoe"]).abs()
        out[zone] = {
            "first_hour": str(j.index.min()),
            "last_hour": str(j.index.max()),
            "n_hours": int(len(j)),
            "corr": float(j["smard"].corr(j["entsoe"])),
            "mean_abs_diff_eur": float(diff.mean()),
            "share_within_0_01": float((diff <= 0.01).mean()),
            "max_abs_diff_eur": float(diff.max()),
            "smard_only_hours": int(a.index.difference(b.index).size),
            "entsoe_only_hours_in_window": int(
                b[(b.index >= a.index.min()) & (b.index <= a.index.max())]
                .index.difference(a.index)
                .size
            ),
        }
    return out
