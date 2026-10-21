"""SFOE weekly PDF ("Montagswerte"), parsed so live weeks need not wait for the CSV.

The CSV (ogd17) has lagged the weekly PDF by about two weeks. The PDF carries the same
numbers: one row per Monday 00:00 with content in GWh and percent for Wallis,
Graubuenden, Tessin, the rest of Switzerland and the total, and the maximum capacity of
each region in the column header of each page. The Rhine flow columns (BAFU data) are
not read.

Files written (all committed, derived from open SFOE data, credit as for the CSV):

- sfoe_storage_pdf.csv: every week ever read from a PDF, latest value per week and
  region, with known_time = the first-seen time of the first logged PDF version that
  contains the week (sfoe_pdf_log.csv). That time is set once and never moved.
- sfoe_storage_merged.csv: CSV values where the CSV has the week, PDF values for newer
  weeks, with a source column (csv or pdf). CSV rows keep the historical Thursday
  known_time; PDF rows use the PDF first-seen time.
- sfoe_merge_log.csv: every PDF value later replaced by a CSV value (or by a revised
  PDF), with the difference.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from alpinehydro import config
from alpinehydro.fetch import sfoe

PDF_DIR = sfoe.RAW_DIR / "pdf"
PDF_TABLE = config.PROCESSED / "sfoe_storage_pdf.csv"
MERGED = config.PROCESSED / "sfoe_storage_merged.csv"
MERGE_LOG = config.PROCESSED / "sfoe_merge_log.csv"

PDF_COLUMNS = [
    "valid_time",
    "known_time",
    "datum",
    "region",
    "content_gwh",
    "max_gwh",
    "fill",
    "pdf_filename",
]
MERGED_COLUMNS = [
    "valid_time",
    "known_time",
    "datum",
    "region",
    "content_gwh",
    "max_gwh",
    "fill",
    "source",
]
MERGE_LOG_COLUMNS = [
    "logged_utc",
    "valid_sunday",
    "region",
    "replaced",
    "by",
    "old_content_gwh",
    "new_content_gwh",
    "diff_gwh",
    "old_max_gwh",
    "new_max_gwh",
]

# Largest difference allowed between the PDF and the CSV in any overlapping week.
TOLERANCE_GWH = 1.0
# The PDF prints percent with one decimal; parsing is rejected if it disagrees by more.
PCT_TOLERANCE = 0.051

_NUM = r"(\d{1,3}(?:'\d{3})*)"
_ROW = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})" + (r"\s+" + _NUM + r"\s+(\d+\.\d)%") * 5)
_MAX = re.compile(r"^" + r"\s+".join([_NUM + r"\s+%"] * 5))


def _int(s: str) -> float:
    return float(s.replace("'", ""))


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- parsing


def parse_text(pages: list[str], filename: str = "") -> pd.DataFrame:
    """Parse the text of each PDF page. Weeks without numbers (future Mondays) are skipped.

    Raises ValueError if a page has rows but no capacity header, or if a printed percent
    does not match content / capacity, so a layout change cannot pass silently.
    """
    regions = config.pipeline()["sfoe"]["regions"]
    rows = []
    for page in pages:
        caps = None
        for line in page.splitlines():
            line = line.strip()
            m = _MAX.match(line)
            if m:
                caps = [_int(g) for g in m.groups()]
                continue
            m = _ROW.match(line)
            if not m:
                continue
            if caps is None:
                raise ValueError(f"{filename}: data row before any capacity header: {line}")
            dd, mm, yyyy, *vals = m.groups()
            datum = pd.Timestamp(f"{yyyy}-{mm}-{dd}")
            if datum.dayofweek != 0:
                raise ValueError(f"{filename}: {datum.date()} is not a Monday")
            for i, region in enumerate(regions):
                content, pct = _int(vals[2 * i]), float(vals[2 * i + 1])
                if abs(content / caps[i] * 100 - pct) > PCT_TOLERANCE:
                    raise ValueError(
                        f"{filename}: {datum.date()} {region}: {content:.0f} of {caps[i]:.0f}"
                        f" GWh is not the printed {pct}%"
                    )
                rows.append(
                    {
                        "datum": datum,
                        "region": region,
                        "content_gwh": content,
                        "max_gwh": caps[i],
                    }
                )
    if not rows:
        raise ValueError(f"{filename}: no data rows found")
    df = pd.DataFrame(rows)
    df["valid_time"] = df["datum"] - pd.Timedelta(days=1)
    df["fill"] = df["content_gwh"] / df["max_gwh"]
    df["pdf_filename"] = filename
    return df.sort_values(["region", "valid_time"]).reset_index(drop=True)


def parse_pdf(path: Path) -> pd.DataFrame:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return parse_text(pages, path.name)


# ---------------------------------------------------------------- known_time


def pdf_known_time(datum: pd.Series, pdf_log: pd.DataFrame) -> pd.Series:
    """First-seen time of the earliest logged PDF version that contains each Monday.

    A version contains Monday M if its filename Monday is M or later in the same year
    (each year has its own PDF). Returns Europe/Zurich timestamps, NaT if none.
    """
    tz = config.pipeline()["sfoe"]["timezone"]
    log = pdf_log.copy()
    log["monday"] = pd.to_datetime(log["monday_in_filename"], errors="coerce")
    log["seen"] = pd.to_datetime(log["first_seen_utc"], utc=True)
    log = log.dropna(subset=["monday", "seen"])
    out = []
    for d in pd.to_datetime(datum):
        ok = log[(log["monday"] >= d) & (log["monday"].dt.year == d.year)]
        out.append(ok["seen"].min() if len(ok) else pd.NaT)
    return pd.Series(pd.to_datetime(out, utc=True), index=datum.index).dt.tz_convert(tz)


# ---------------------------------------------------------------- files


def _write_if_changed(path: Path, header: list[str], body: str) -> bool:
    if path.exists():
        old = "".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.startswith("#")
        )
        if old == body:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(f"# {h}" for h in header) + "\n" + body).encode("utf-8"))
    return True


def _fmt(df: pd.DataFrame, columns: list[str]) -> str:
    out = df[columns].copy()
    out["valid_time"] = pd.to_datetime(out["valid_time"]).dt.strftime("%Y-%m-%d")
    out["datum"] = pd.to_datetime(out["datum"]).dt.strftime("%Y-%m-%d")
    out["known_time"] = out["known_time"].map(lambda t: t.isoformat() if pd.notna(t) else "")
    out["fill"] = out["fill"].round(6)
    out = out.sort_values(["region", "valid_time"])
    return out.to_csv(index=False, lineterminator="\n")


def _read(path: Path) -> pd.DataFrame:
    tz = config.pipeline()["sfoe"]["timezone"]
    df = pd.read_csv(path, comment="#")
    for c in ("valid_time", "datum"):
        df[c] = pd.to_datetime(df[c])
    df["known_time"] = pd.to_datetime(df["known_time"], utc=True).dt.tz_convert(tz)
    return df


def load_pdf_table(path: Path = PDF_TABLE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PDF_COLUMNS)
    return _read(path)


def load_merged(path: Path = MERGED) -> pd.DataFrame:
    """The live storage table (CSV plus newer PDF weeks). Needs no network and no keys."""
    return _read(path)


def _append_log(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    old = (
        pd.read_csv(path, dtype=str, keep_default_na=False)
        if path.exists()
        else pd.DataFrame(columns=MERGE_LOG_COLUMNS)
    )
    out = pd.concat([old, pd.DataFrame(rows).astype(str)], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out[MERGE_LOG_COLUMNS].to_csv(index=False, lineterminator="\n").encode())


def upsert_pdf_table(
    parsed: pd.DataFrame,
    pdf_log: pd.DataFrame,
    path: Path = PDF_TABLE,
    log_path: Path = MERGE_LOG,
    now: str | None = None,
) -> dict:
    """Add new PDF weeks and apply revisions; keep each week's first known_time."""
    now = now or _now_utc()
    old = load_pdf_table(path)
    new = parsed.copy()
    new["known_time"] = pdf_known_time(new["datum"], pdf_log)
    key = ["valid_time", "region"]
    if len(old):
        both = new.merge(
            old[[*key, "known_time", "content_gwh", "max_gwh"]],
            on=key,
            how="left",
            suffixes=("", "_old"),
        )
        keep = both["known_time_old"].notna()
        both.loc[keep, "known_time"] = both.loc[keep, "known_time_old"]
        rev = both[
            keep
            & (
                (both["content_gwh"] != both["content_gwh_old"])
                | (both["max_gwh"] != both["max_gwh_old"])
            )
        ]
        _append_log(
            [
                {
                    "logged_utc": now,
                    "valid_sunday": r.valid_time.strftime("%Y-%m-%d"),
                    "region": r.region,
                    "replaced": "pdf",
                    "by": f"pdf revision ({r.pdf_filename})",
                    "old_content_gwh": r.content_gwh_old,
                    "new_content_gwh": r.content_gwh,
                    "diff_gwh": r.content_gwh - r.content_gwh_old,
                    "old_max_gwh": r.max_gwh_old,
                    "new_max_gwh": r.max_gwh,
                }
                for r in rev.itertuples()
            ],
            log_path,
        )
        new = both[PDF_COLUMNS]
        rest = old.merge(new[key], on=key, how="left", indicator=True)
        rest = rest[rest["_merge"] == "left_only"][PDF_COLUMNS]
        table = pd.concat([rest, new], ignore_index=True)
        revised = len(rev)
    else:
        table, revised = new[PDF_COLUMNS], 0
    header = [
        f"credit: {sfoe.CREDIT}",
        "source: SFOE weekly PDF 'Montagswerte' (pubdb.bfe.admin.ch), parsed with pdfplumber",
        "one row per week and region; the latest PDF value; Rhine flow columns not read",
        "known_time: first-seen time of the first logged PDF version holding the week",
        "(data/processed/sfoe_pdf_log.csv); set once, never moved",
    ]
    changed = _write_if_changed(path, header, _fmt(table, PDF_COLUMNS))
    return {"pdf_weeks": int(table["valid_time"].nunique()), "revised": revised, "changed": changed}


def crosscheck(csv: pd.DataFrame, pdf: pd.DataFrame) -> pd.DataFrame:
    """Every overlapping week and region, with content and capacity differences."""
    key = ["valid_time", "region"]
    m = csv[[*key, "content_gwh", "max_gwh"]].merge(
        pdf[[*key, "content_gwh", "max_gwh"]], on=key, suffixes=("_csv", "_pdf")
    )
    m["diff_content_gwh"] = m["content_gwh_pdf"] - m["content_gwh_csv"]
    m["diff_max_gwh"] = m["max_gwh_pdf"] - m["max_gwh_csv"]
    return m


def merge(
    csv: pd.DataFrame,
    pdf: pd.DataFrame,
    path: Path = MERGED,
    log_path: Path = MERGE_LOG,
    now: str | None = None,
) -> dict:
    """CSV where it has the week, PDF for newer weeks. Logs PDF values the CSV replaced."""
    now = now or _now_utc()
    key = ["valid_time", "region"]
    c = csv.assign(source="csv")
    have = c[key].assign(_in_csv=True)
    p = pdf.merge(have, on=key, how="left")
    p = p[p["_in_csv"].isna()].drop(columns="_in_csv").assign(source="pdf")
    table = pd.concat([c[MERGED_COLUMNS], p[MERGED_COLUMNS]], ignore_index=True)

    replaced = []
    if path.exists():
        old = load_merged(path)
        was_pdf = old[old["source"] == "pdf"]
        now_csv = was_pdf.merge(c[[*key, "content_gwh", "max_gwh"]], on=key, suffixes=("_old", ""))
        replaced = [
            {
                "logged_utc": now,
                "valid_sunday": r.valid_time.strftime("%Y-%m-%d"),
                "region": r.region,
                "replaced": "pdf",
                "by": "csv",
                "old_content_gwh": r.content_gwh_old,
                "new_content_gwh": r.content_gwh,
                "diff_gwh": r.content_gwh - r.content_gwh_old,
                "old_max_gwh": r.max_gwh_old,
                "new_max_gwh": r.max_gwh,
            }
            for r in now_csv.itertuples()
        ]
    header = [
        f"credit: {sfoe.CREDIT}",
        "SFOE storage for live use: CSV (ogd17) where it has the week, weekly PDF for newer",
        "weeks. source = csv or pdf. CSV rows: known_time = Thursday 23:59 Europe/Zurich",
        "after valid_time (historical rule). PDF rows: known_time = PDF first-seen time.",
        "Backtests use sfoe_storage_weekly.csv (CSV only), not this file.",
    ]
    changed = _write_if_changed(path, header, _fmt(table, MERGED_COLUMNS))
    if changed:
        _append_log(replaced, log_path)
    else:
        replaced = []
    latest = table[table["region"] == "TotalCH"].sort_values("valid_time").iloc[-1]
    return {
        "latest_week": latest["valid_time"].strftime("%Y-%m-%d"),
        "latest_source": latest["source"],
        "pdf_weeks_in_merged": int((p["region"] == "TotalCH").sum()),
        "replaced_by_csv": [
            {"week": r["valid_sunday"], "region": r["region"], "diff_gwh": r["diff_gwh"]}
            for r in replaced
        ],
        "changed": changed,
    }


def latest_cached_pdfs() -> list[Path]:
    """The newest cached PDF of each year (by the Monday in the filename)."""
    best: dict[str, tuple[str, Path]] = {}
    for p in PDF_DIR.glob("*.pdf"):
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", p.name)
        if not m:
            continue
        monday = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if m.group(3) not in best or monday > best[m.group(3)][0]:
            best[m.group(3)] = (monday, p)
    return [p for _, p in sorted(best.values())]


def update(refresh_csv: bool = False) -> dict:
    """Refresh the CSV table, parse the cached PDFs and rebuild the merged table.

    Needs only the files cached by log-release (no keys). Raises if any overlapping week
    of the CSV and the PDF differs by more than TOLERANCE_GWH.
    """
    csv, csv_changed = sfoe.fetch(refresh=refresh_csv)
    pdfs = latest_cached_pdfs()
    if not pdfs:
        raise RuntimeError("no cached SFOE PDF; run log-release first")
    parsed = pd.concat([parse_pdf(p) for p in pdfs], ignore_index=True)
    pdf_log = pd.read_csv(sfoe.PDF_LOG, dtype=str, keep_default_na=False)
    up = upsert_pdf_table(parsed, pdf_log)
    pdf = load_pdf_table()
    x = crosscheck(csv, pdf)
    worst = float(x[["diff_content_gwh", "diff_max_gwh"]].abs().max().max()) if len(x) else 0.0
    if worst > TOLERANCE_GWH:
        raise RuntimeError(f"PDF and CSV differ by {worst} GWh in an overlapping week")
    mg = merge(csv, pdf)
    return {
        "csv_changed": csv_changed,
        "pdf_files": [p.name for p in pdfs],
        **{f"pdf_{k}": v for k, v in up.items()},
        "overlap_weeks": int(x["valid_time"].nunique()),
        "overlap_max_abs_diff_gwh": worst,
        **{f"merged_{k}": v for k, v in mg.items()},
    }
