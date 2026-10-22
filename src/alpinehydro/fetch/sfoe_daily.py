"""SFOE production and pumping for the water balance (post-hoc, prereg/WATER_BALANCE_PLAN.md).

- ogd104 (energy dashboard, "Stromproduktion Swissgrid"): daily production in GWh by
  technology from 2015. "Speicherkraft" is storage plus pumped-storage generation. It has
  no pumping. Built from Swissgrid data, the same origin as ENTSO-E.
- ogd35 (electricity balance, monthly values): storage-plant generation and pumping
  (Verbrauch_Speicherpumpen_GWh) from 2000. Recent months are provisional (Definitiv 0).

Raw files are cached in data/raw/sfoe_daily/ (git-ignored). Open use with credit:
Source: Swiss Federal Office of Energy SFOE.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from alpinehydro import config
from alpinehydro.fetch.sfoe import HEADERS, TIMEOUT

RAW_DIR = config.RAW / "sfoe_daily"
URLS = {
    "ogd104": "https://www.bfe-ogd.ch/ogd104_stromproduktion_swissgrid.csv",
    "ogd35": "https://www.bfe-ogd.ch/ogd35/ogd35_schweizerische_elektrizitaetsbilanz_monatswerte.csv",
}


def download(name: str, refresh: bool = False) -> tuple[Path, dict]:
    """Download one SFOE file to data/raw/sfoe_daily/, or reuse the cached copy."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.csv"
    meta_path = path.with_suffix(".meta.json")
    if path.exists() and meta_path.exists() and not refresh:
        return path, json.loads(meta_path.read_text(encoding="utf-8"))
    r = requests.get(URLS[name], timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    path.write_bytes(r.content)
    meta = {
        "url": URLS[name],
        "downloaded_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "http_last_modified": r.headers.get("Last-Modified", ""),
        "sha256": hashlib.sha256(r.content).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path, meta


def daily_storage_production(path: Path | None = None) -> pd.Series:
    """ogd104 'Speicherkraft' in GWh per local day. Days without a value are dropped."""
    path = path or download("ogd104")[0]
    d = pd.read_csv(path, encoding="utf-8-sig")
    d = d[d["Energietraeger"] == "Speicherkraft"]
    s = pd.Series(
        d["Produktion_GWh"].astype(float).to_numpy(),
        index=pd.to_datetime(d["Datum"], format="%Y-%m-%d"),
        name="speicherkraft_gwh",
    )
    s.index.name = "day"
    return s.dropna().sort_index()


def monthly_balance(path: Path | None = None) -> pd.DataFrame:
    """ogd35: one row per month with storage-plant generation and pumping, in GWh."""
    path = path or download("ogd35")[0]
    d = pd.read_csv(path, encoding="utf-8-sig", na_values=["NULL"])
    out = pd.DataFrame(
        {
            "month": pd.to_datetime(dict(year=d["Jahr"], month=d["Monat"], day=1)),
            "gen_storage_gwh": d["Erzeugung_Speicherwerk_GWh"].astype(float),
            "pumping_gwh": d["Verbrauch_Speicherpumpen_GWh"].astype(float),
            "definitive": d["Definitiv"].astype(int).astype(bool),
        }
    )
    return out.dropna(subset=["pumping_gwh"]).set_index("month").sort_index()


def daily_pumping(monthly: pd.DataFrame) -> pd.Series:
    """Monthly pumping spread evenly over the calendar days of its month (plan section 2)."""
    parts = []
    for month, row in monthly.iterrows():
        days = pd.date_range(month, month + pd.offsets.MonthEnd(0), freq="D")
        parts.append(pd.Series(row["pumping_gwh"] / len(days), index=days))
    s = pd.concat(parts).sort_index()
    s.index.name = "day"
    return s.rename("pumping_gwh")


def sfoe_weeks(daily: pd.Series) -> pd.DataFrame:
    """Sum a daily GWh series over SFOE weeks (Monday to Sunday). Only full 7-day weeks.

    valid_time is the Sunday that ends the week.
    """
    week_end = daily.index + pd.to_timedelta(6 - daily.index.dayofweek, unit="D")
    g = daily.groupby(week_end)
    out = pd.DataFrame({"gwh": g.sum(), "n_days": g.count()})
    out = out[out["n_days"] == 7]
    out.index.name = "valid_time"
    return out
