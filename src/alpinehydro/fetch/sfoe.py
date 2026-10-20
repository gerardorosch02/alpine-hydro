"""SFOE weekly storage of Swiss reservoirs (open data set ogd17).

Datum in the CSV is a Monday 00:00 and describes the content at Sunday 24:00,
so valid_time is the Sunday before Datum. Historical known_time is a
conservative Thursday 23:59 Europe/Zurich after that Sunday.

The release log records, from now on, when a new CSV week and a new weekly PDF
are first seen. The PDF is watched by its HTTP headers and file hash only; it
is not parsed.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from alpinehydro import config

CREDIT = "Source: Swiss Federal Office of Energy SFOE"
TIMEOUT = 60
HEADERS = {"User-Agent": "alpinehydro research project (github.com/gerardorosch02)"}

RAW_DIR = config.RAW / "sfoe"
STORAGE_CSV = config.PROCESSED / "sfoe_storage_weekly.csv"
RELEASE_LOG = config.PROCESSED / "sfoe_release_log.csv"
PDF_LOG = config.PROCESSED / "sfoe_pdf_log.csv"

RELEASE_COLUMNS = ["valid_sunday", "first_seen_utc", "method", "http_last_modified"]
PDF_COLUMNS = [
    "first_seen_utc",
    "pdf_url",
    "filename",
    "monday_in_filename",
    "http_last_modified",
    "sha256",
    "bytes",
]


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- download


def download_csv(refresh: bool = False) -> tuple[Path, dict]:
    """Download the CSV to data/raw/sfoe/, or reuse the cached copy."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "ogd17_fuellungsgrad_speicherseen.csv"
    meta_path = path.with_suffix(".meta.json")
    if path.exists() and meta_path.exists() and not refresh:
        return path, json.loads(meta_path.read_text(encoding="utf-8"))
    url = config.pipeline()["sfoe"]["csv_url"]
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    path.write_bytes(r.content)
    meta = {
        "url": url,
        "downloaded_utc": _now_utc(),
        "http_last_modified": r.headers.get("Last-Modified", ""),
        "sha256": hashlib.sha256(r.content).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path, meta


# ---------------------------------------------------------------- parsing


def known_time_for(valid_sunday: pd.Series) -> pd.Series:
    """Conservative historical known_time: Thursday 23:59 Europe/Zurich after the Sunday."""
    cfg = config.pipeline()["sfoe"]
    days_after_sunday = cfg["known_time_weekday"] + 1  # Sunday -> Thursday is 4 days
    hh, mm = (int(x) for x in cfg["known_time_clock"].split(":"))
    local = pd.to_datetime(valid_sunday) + pd.Timedelta(days=days_after_sunday)
    local = local + pd.Timedelta(hours=hh, minutes=mm)
    return local.dt.tz_localize(cfg["timezone"])


def parse_csv(text: str) -> pd.DataFrame:
    """Turn the wide SFOE CSV into a tidy long table, one row per week and region."""
    wide = pd.read_csv(io.StringIO(text))
    wide["Datum"] = pd.to_datetime(wide["Datum"], format="%Y-%m-%d")
    if not (wide["Datum"].dt.dayofweek == 0).all():
        bad = wide.loc[wide["Datum"].dt.dayofweek != 0, "Datum"].dt.date.tolist()
        raise ValueError(f"Datum values that are not Mondays: {bad[:5]}")
    rows = []
    for region in config.pipeline()["sfoe"]["regions"]:
        part = pd.DataFrame(
            {
                "datum": wide["Datum"],
                "region": region,
                "content_gwh": wide[f"{region}_speicherinhalt_gwh"].astype(float),
                "max_gwh": wide[f"{region}_max_speicherinhalt_gwh"].astype(float),
            }
        )
        rows.append(part)
    df = pd.concat(rows, ignore_index=True)
    df["valid_time"] = df["datum"] - pd.Timedelta(days=1)
    df["known_time"] = known_time_for(df["valid_time"])
    df["fill"] = df["content_gwh"] / df["max_gwh"]
    df = df.sort_values(["region", "valid_time"]).reset_index(drop=True)
    return df[["valid_time", "known_time", "datum", "region", "content_gwh", "max_gwh", "fill"]]


# ---------------------------------------------------------------- processed file


def _format_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["valid_time"] = out["valid_time"].dt.strftime("%Y-%m-%d")
    out["datum"] = out["datum"].dt.strftime("%Y-%m-%d")
    out["known_time"] = out["known_time"].map(lambda t: t.isoformat())
    out["fill"] = out["fill"].round(6)
    return out


def write_processed(df: pd.DataFrame, meta: dict, path: Path = STORAGE_CSV) -> bool:
    """Write the tidy table with a provenance header. Returns True if the file changed.

    If the data rows are identical to the existing file, nothing is rewritten, so
    repeated runs do not create noise in Git.
    """
    body = _format_for_csv(df).to_csv(index=False, lineterminator="\n")
    if path.exists():
        old_body = "".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.startswith("#")
        )
        if old_body == body:
            return False
    header = [
        f"# source: {meta['url']}",
        f"# credit: {CREDIT}",
        f"# downloaded_utc: {meta['downloaded_utc']}",
        f"# source_last_modified: {meta.get('http_last_modified', '')}",
        f"# rows: {len(df)}",
        "# valid_time: the Sunday 24:00 that Datum (a Monday 00:00) describes",
        "# known_time: conservative Thursday 23:59 Europe/Zurich after valid_time",
        "# fill: content_gwh / max_gwh of the same week",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + "\n" + body, encoding="utf-8")
    return True


def load_processed(path: Path = STORAGE_CSV) -> pd.DataFrame:
    """Read the committed storage table. Needs no network and no keys."""
    df = pd.read_csv(path, comment="#")
    df["valid_time"] = pd.to_datetime(df["valid_time"])
    df["datum"] = pd.to_datetime(df["datum"])
    df["known_time"] = pd.to_datetime(df["known_time"], utc=True).dt.tz_convert(
        config.pipeline()["sfoe"]["timezone"]
    )
    return df


def fetch(refresh: bool = False) -> tuple[pd.DataFrame, bool]:
    path, meta = download_csv(refresh=refresh)
    df = parse_csv(path.read_text(encoding="utf-8"))
    changed = write_processed(df, meta)
    return df, changed


# ---------------------------------------------------------------- release log


def _read_log(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=columns)


def update_release_log(
    sundays: list[str], seen_utc: str, http_last_modified: str, path: Path = RELEASE_LOG
) -> list[str]:
    """Append weeks not yet in the log. Returns the Sundays that were added.

    On an empty log only the latest week is recorded, with method "baseline",
    because its first_seen_utc is only an upper bound on the true release time.
    """
    log = _read_log(path, RELEASE_COLUMNS)
    sundays = sorted(set(sundays))
    if log.empty:
        new = sundays[-1:]
        method = "baseline"
    else:
        last = max(log["valid_sunday"])
        new = [s for s in sundays if s > last]
        method = "csv_poll"
    if not new:
        return []
    add = pd.DataFrame(
        {
            "valid_sunday": new,
            "first_seen_utc": seen_utc,
            "method": method,
            "http_last_modified": http_last_modified,
        }
    )
    out = pd.concat([log, add], ignore_index=True)[RELEASE_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    return new


def current_pdf_url() -> str:
    """Find the current-year weekly PDF: the first download link on the collection page."""
    cfg = config.pipeline()["sfoe"]
    r = requests.get(cfg["pdf_collection_url"], timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    ids = re.findall(r"publication/download/(\d+)", r.text)
    if not ids:
        raise RuntimeError("No PDF link found on the SFOE collection page")
    return cfg["pdf_download_base"] + ids[0]


def update_pdf_log(
    pdf_url: str,
    content: bytes,
    filename: str,
    http_last_modified: str,
    seen_utc: str,
    path: Path = PDF_LOG,
) -> bool:
    """Append a row when the PDF content differs from the last logged version."""
    log = _read_log(path, PDF_COLUMNS)
    digest = hashlib.sha256(content).hexdigest()
    if not log.empty and log["sha256"].iloc[-1] == digest:
        return False
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", filename)
    monday = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
    row = pd.DataFrame(
        [
            {
                "first_seen_utc": seen_utc,
                "pdf_url": pdf_url,
                "filename": filename,
                "monday_in_filename": monday,
                "http_last_modified": http_last_modified,
                "sha256": digest,
                "bytes": str(len(content)),
            }
        ]
    )
    out = pd.concat([log, row], ignore_index=True)[PDF_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    return True


def log_release() -> dict:
    """Download the CSV and the current PDF, and log anything new."""
    seen = _now_utc()
    csv_path, meta = download_csv(refresh=True)
    df = parse_csv(csv_path.read_text(encoding="utf-8"))
    sundays = df["valid_time"].dt.strftime("%Y-%m-%d").unique().tolist()
    added = update_release_log(sundays, seen, meta["http_last_modified"])

    result = {"csv_latest_sunday": max(sundays), "csv_new_weeks": added}
    try:
        pdf_url = current_pdf_url()
        r = requests.get(pdf_url, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        filename = m.group(1) if m else ""
        pdf_dir = RAW_DIR / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        if filename:
            (pdf_dir / filename).write_bytes(r.content)
        changed = update_pdf_log(
            pdf_url, r.content, filename, r.headers.get("Last-Modified", ""), seen
        )
        result.update({"pdf_filename": filename, "pdf_changed": changed})
    except requests.RequestException as exc:
        result["pdf_error"] = f"{type(exc).__name__}: {exc}"
    return result
