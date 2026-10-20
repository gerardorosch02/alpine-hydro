import pandas as pd
import pytest

from alpinehydro.fetch import sfoe

REGIONS = ["Wallis", "Graubuenden", "Tessin", "UebrigCH", "TotalCH"]


def make_csv(mondays: list[str], total: list[int], max_total: int = 8895) -> str:
    cols = ["Datum"] + [f"{r}_speicherinhalt_gwh" for r in REGIONS]
    cols += [f"{r}_max_speicherinhalt_gwh" for r in REGIONS]
    lines = [",".join(cols)]
    for d, t in zip(mondays, total, strict=True):
        vals = [d, "1", "1", "1", "1", str(t), "2", "2", "2", "2", str(max_total)]
        lines.append(",".join(vals))
    return "\n".join(lines) + "\n"


def test_valid_time_is_sunday_and_known_time_is_thursday():
    df = sfoe.parse_csv(make_csv(["2026-01-05", "2026-07-06"], [4685, 3799]))
    t = df[df["region"] == "TotalCH"].reset_index(drop=True)
    assert list(t["valid_time"].dt.strftime("%Y-%m-%d")) == ["2026-01-04", "2026-07-05"]
    assert (t["valid_time"].dt.dayofweek == 6).all()
    # Thursday 23:59 Zurich, winter CET and summer CEST
    assert t["known_time"][0].isoformat() == "2026-01-08T23:59:00+01:00"
    assert t["known_time"][1].isoformat() == "2026-07-09T23:59:00+02:00"
    assert t["fill"][0] == pytest.approx(4685 / 8895)


def test_non_monday_datum_is_rejected():
    with pytest.raises(ValueError):
        sfoe.parse_csv(make_csv(["2026-01-06"], [4000]))


def test_write_processed_is_idempotent(tmp_path):
    df = sfoe.parse_csv(make_csv(["2026-01-05", "2026-01-12"], [4685, 4195]))
    meta = {"url": "u", "downloaded_utc": "t1", "http_last_modified": ""}
    path = tmp_path / "s.csv"
    assert sfoe.write_processed(df, meta, path)
    meta["downloaded_utc"] = "t2"
    assert not sfoe.write_processed(df, meta, path)  # same rows: file untouched
    assert "t1" in path.read_text()
    back = sfoe.load_processed(path)
    assert len(back) == len(df)
    assert back["known_time"].iloc[0] == df["known_time"].iloc[0]


def test_release_log_baseline_then_new_weeks(tmp_path):
    path = tmp_path / "log.csv"
    added = sfoe.update_release_log(["2026-09-20", "2026-09-27"], "T0", "LM0", path)
    assert added == ["2026-09-27"]
    assert sfoe.update_release_log(["2026-09-20", "2026-09-27"], "T1", "LM0", path) == []
    added = sfoe.update_release_log(["2026-09-27", "2026-10-04", "2026-10-11"], "T2", "LM1", path)
    assert added == ["2026-10-04", "2026-10-11"]
    log = pd.read_csv(path, dtype=str)
    assert list(log.columns) == sfoe.RELEASE_COLUMNS
    assert list(log["method"]) == ["baseline", "csv_poll", "csv_poll"]
    assert list(log["first_seen_utc"]) == ["T0", "T2", "T2"]


def test_pdf_log_records_only_changes(tmp_path):
    path = tmp_path / "pdf.csv"
    name = "12445-Montagswerte_12.10.2026.pdf"
    assert sfoe.update_pdf_log("u", b"a", name, "LM", "T0", path)
    assert not sfoe.update_pdf_log("u", b"a", name, "LM", "T1", path)
    assert sfoe.update_pdf_log("u", b"b", name.replace("12.10", "19.10"), "LM2", "T2", path)
    log = pd.read_csv(path, dtype=str)
    assert list(log["monday_in_filename"]) == ["2026-10-12", "2026-10-19"]
    assert list(log["first_seen_utc"]) == ["T0", "T2"]
