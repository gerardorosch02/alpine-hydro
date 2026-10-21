import pandas as pd
import pytest

from alpinehydro.fetch import sfoe, sfoe_pdf

# Two lines copied from the layout of 12445-Montagswerte_12.10.2026.pdf (page 2), plus an
# empty future Monday. The last three numbers are the Rhine flow columns, never read.
PAGE = """Speicherinhalt - Contenu des bassins d'accumulation
GWh GWh GWh GWh GWh de longue date effectif
4'070 % 1'980 % 1'245 % 1'600 % 8'895 % m3/s / 1933-2021 m3/s / 12:00h %
Montag / Lundi
28.09.2026 3'453 84.8% 1'316 66.5% 628 50.4% 1'191 74.4% 6'588 74.1% 945 332 35%
05.10.2026 3'440 84.5% 1'307 66.0% 649 52.1% 1'176 73.5% 6'572 73.9% 889 333 37%
12.10.2026
"""


def test_committed_pdf_and_csv_agree_on_every_overlapping_week():
    csv = sfoe.load_processed()
    pdf = sfoe_pdf.load_pdf_table()
    x = sfoe_pdf.crosscheck(csv, pdf)
    assert x["valid_time"].nunique() >= 1
    assert x["diff_content_gwh"].abs().max() <= sfoe_pdf.TOLERANCE_GWH
    assert x["diff_max_gwh"].abs().max() <= sfoe_pdf.TOLERANCE_GWH


def test_parse_text_reads_every_region_and_capacity():
    df = sfoe_pdf.parse_text([PAGE], "f.pdf")
    assert len(df) == 10  # 2 weeks x 5 regions; the empty Monday is skipped
    t = df[df["region"] == "TotalCH"].reset_index(drop=True)
    assert list(t["valid_time"].dt.strftime("%Y-%m-%d")) == ["2026-09-27", "2026-10-04"]
    assert list(t["content_gwh"]) == [6588, 6572]
    assert (t["max_gwh"] == 8895).all()
    w = df[(df["region"] == "Wallis")].iloc[0]
    assert w["content_gwh"] == 3453 and w["max_gwh"] == 4070


def test_parse_text_rejects_a_percent_that_does_not_match():
    bad = PAGE.replace("6'588 74.1%", "6'588 70.1%")
    with pytest.raises(ValueError, match="printed"):
        sfoe_pdf.parse_text([bad], "f.pdf")


def test_parse_text_rejects_rows_without_capacity_header():
    with pytest.raises(ValueError, match="capacity"):
        sfoe_pdf.parse_text(["28.09.2026 " + PAGE.splitlines()[4][11:]], "f.pdf")


def _log(rows):
    return pd.DataFrame(rows, columns=["first_seen_utc", "monday_in_filename"])


def test_pdf_known_time_is_first_version_holding_the_week():
    log = _log([["2026-10-20T13:57:25Z", "2026-10-12"], ["2026-10-27T08:00:00Z", "2026-10-19"]])
    kt = sfoe_pdf.pdf_known_time(
        pd.Series(pd.to_datetime(["2026-10-05", "2026-10-19", "2026-10-26"])), log
    )
    assert kt[0].isoformat() == "2026-10-20T15:57:25+02:00"
    assert kt[1].isoformat() == "2026-10-27T09:00:00+01:00"  # CET after 25 Oct
    assert pd.isna(kt[2])


def _week(sunday, content, kt=None):
    s = pd.Timestamp(sunday)
    return {
        "valid_time": s,
        "known_time": kt if kt is not None else pd.Timestamp(s, tz="Europe/Zurich"),
        "datum": s + pd.Timedelta(days=1),
        "region": "TotalCH",
        "content_gwh": float(content),
        "max_gwh": 8895.0,
        "fill": content / 8895,
        "pdf_filename": "f.pdf",
    }


def test_merge_rule_csv_first_pdf_newer_and_csv_replaces_with_log(tmp_path):
    out, log = tmp_path / "m.csv", tmp_path / "log.csv"
    csv = pd.DataFrame([_week("2026-09-27", 6588)])
    pdf = pd.DataFrame([_week("2026-09-27", 6588), _week("2026-10-04", 6572)])
    r = sfoe_pdf.merge(csv, pdf, out, log, now="T1")
    m = sfoe_pdf.load_merged(out)
    assert list(m["source"]) == ["csv", "pdf"]
    assert r["latest_week"] == "2026-10-04" and r["latest_source"] == "pdf"
    assert not log.exists()

    # Nothing new: the file and the log are untouched.
    before = out.read_bytes()
    r = sfoe_pdf.merge(csv, pdf, out, log, now="T2")
    assert not r["changed"] and out.read_bytes() == before and not log.exists()

    # The CSV catches up with a slightly different value: CSV wins, the difference is logged.
    csv2 = pd.DataFrame([_week("2026-09-27", 6588), _week("2026-10-04", 6573)])
    r = sfoe_pdf.merge(csv2, pdf, out, log, now="T3")
    m = sfoe_pdf.load_merged(out)
    assert list(m["source"]) == ["csv", "csv"]
    assert m["content_gwh"].iloc[-1] == 6573
    g = pd.read_csv(log)
    assert list(g["valid_sunday"]) == ["2026-10-04"]
    assert g["by"].iloc[0] == "csv" and g["diff_gwh"].iloc[0] == 1.0
    assert r["replaced_by_csv"] == [{"week": "2026-10-04", "region": "TotalCH", "diff_gwh": 1.0}]


def test_upsert_keeps_first_known_time_and_logs_revisions(tmp_path):
    out, log = tmp_path / "p.csv", tmp_path / "log.csv"
    pdf_log = _log([["2026-10-20T13:57:25Z", "2026-10-12"]])
    first = pd.DataFrame([_week("2026-10-11", 6551)]).drop(columns="known_time")
    sfoe_pdf.upsert_pdf_table(first, pdf_log, out, log, now="T1")
    kt0 = sfoe_pdf.load_pdf_table(out)["known_time"].iloc[0]

    pdf_log2 = _log([["2026-10-27T08:00:00Z", "2026-10-19"]])  # earlier row "forgotten"
    revised = pd.DataFrame([_week("2026-10-11", 6550), _week("2026-10-18", 6530)]).drop(
        columns="known_time"
    )
    r = sfoe_pdf.upsert_pdf_table(revised, pdf_log2, out, log, now="T2")
    t = sfoe_pdf.load_pdf_table(out).sort_values("valid_time")
    assert t["known_time"].iloc[0] == kt0  # never moved
    assert t["content_gwh"].iloc[0] == 6550  # revision applied
    assert r["revised"] == 1
    assert pd.read_csv(log)["by"].iloc[0].startswith("pdf revision")
