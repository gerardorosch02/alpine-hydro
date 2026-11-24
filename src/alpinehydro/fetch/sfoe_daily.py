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
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from alpinehydro import config
from alpinehydro.fetch import sfoe
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
    check(name, r.content)  # before the cache is replaced
    path.write_bytes(r.content)
    meta = {
        "url": URLS[name],
        "downloaded_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "http_last_modified": r.headers.get("Last-Modified", ""),
        "sha256": hashlib.sha256(r.content).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path, meta


def last_date(name: str, text: str) -> pd.Timestamp:
    """Newest date with data: ogd104 the last day with a Speicherkraft value, ogd35 the
    last day of the last month with pumping. Lines that are not data rows are skipped."""
    lines = text.splitlines()
    if name == "ogd104":
        days = re.findall(r"^(\d{4}-\d{2}-\d{2}),Speicherkraft,-?\d", text, flags=re.MULTILINE)
        if days:
            return pd.Timestamp(max(days))
    else:
        head = next((ln.split(",") for ln in lines if ln.startswith("Jahr,")), [])
        rows = [ln.split(",") for ln in lines if re.match(r"^\d{4},\d{1,2},", ln)]
        if "Verbrauch_Speicherpumpen_GWh" in head:
            i = head.index("Verbrauch_Speicherpumpen_GWh")
            months = [
                pd.Timestamp(year=int(r[0]), month=int(r[1]), day=1)
                for r in rows
                if len(r) > i and r[i] not in ("", "NULL")
            ]
            if months:
                return max(months) + pd.offsets.MonthEnd(0)
    raise sfoe.SourceStopped(f"{name}: no dated row with data in the file")


def check(name: str, content: bytes, today: pd.Timestamp | None = None) -> pd.Timestamp:
    """Raise sfoe.SourceStopped if the file is stopped or stale; return its newest date."""
    text = sfoe.decode(content)
    sfoe.check_notice(name, text, URLS[name])  # first: a stopped file may still parse
    last = last_date(name, text)
    sfoe.check_source(name, text, last, today, URLS[name])
    return last


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
