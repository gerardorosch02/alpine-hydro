"""SFOE source files: a stopped or moved file must fail loudly, never be read quietly.

In 2026 SFOE moved its open data from www.uvek-gis.admin.ch to www.bfe-ogd.ch. The old
ogd35 file got the line "Diese Daten werden nicht mehr weitergeführt. Neuer Link: ...";
the old ogd17 and ogd104 files just stopped, with no notice. The pipeline read the old
ogd17 address from 29 September to 24 November 2026 without noticing.

The offline tests run everywhere. The live test downloads the three files and runs only
with ALPINEHYDRO_NETWORK=1 (the keyless sfoe-check Action sets it).
"""

import os
import re
from pathlib import Path

import pandas as pd
import pytest
import requests

from alpinehydro import config
from alpinehydro.fetch import sfoe, sfoe_daily

ROOT = Path(__file__).resolve().parents[1]
NOTICE = (
    "Diese Daten werden nicht mehr weitergeführt. Neuer Link: "
    "https://www.bfe-ogd.ch/ogd35/ogd35_schweizerische_elektrizitaetsbilanz_monatswerte.csv"
    " - Öffnet in einem neuen Tab."
)
OGD35 = (
    "Jahr,Monat,Definitiv,Erzeugung_Speicherwerk_GWh,Verbrauch_Speicherpumpen_GWh\n"
    "2026,6,0,1807,694\n"
    "2026,7,0,1303,690\n"
)
OGD104 = (
    "Datum,Energietraeger,Produktion_GWh\n"
    "2026-06-13,Speicherkraft,23.9\n"
    "2026-06-14,Speicherkraft,-1.5\n"
    "2026-06-15,Speicherkraft,\n"
    "2026-06-15,Thermische,7.3\n"
)
OGD17 = "Datum,TotalCH_speicherinhalt_gwh\n2026-09-21,6639\n2026-09-28,6588\n"


def test_stop_notice_is_caught_in_cp1252_as_sfoe_serves_it():
    content = (NOTICE + "\n" + OGD35 + NOTICE).encode("cp1252")
    with pytest.raises(sfoe.SourceStopped, match="has stopped this file"):
        sfoe_daily.check("ogd35", content, today=pd.Timestamp("2026-08-20"))


def test_stop_notice_is_caught_in_every_file_even_when_the_dates_are_fresh():
    for name, body, today in (
        ("ogd17", OGD17, "2026-09-30"),
        ("ogd104", OGD104, "2026-06-16"),
        ("ogd35", OGD35, "2026-08-20"),
    ):
        with pytest.raises(sfoe.SourceStopped, match="has stopped this file"):
            sfoe.check_notice(name, body + NOTICE + "\n")
        with pytest.raises(sfoe.SourceStopped):
            sfoe.check_source(name, NOTICE + "\n" + body, pd.Timestamp(today), pd.Timestamp(today))


def test_newest_date_is_the_last_one_with_data():
    assert sfoe.last_datum(OGD17) == pd.Timestamp("2026-09-28")
    # the empty Speicherkraft row of 15 June and other categories do not count
    assert sfoe_daily.last_date("ogd104", OGD104) == pd.Timestamp("2026-06-14")
    assert sfoe_daily.last_date("ogd35", OGD35) == pd.Timestamp("2026-07-31")
    assert sfoe_daily.last_date("ogd35", OGD35 + "2026,8,0,1631,NULL\n") == pd.Timestamp(
        "2026-07-31"
    )
    with pytest.raises(sfoe.SourceStopped, match="no dated row"):
        sfoe_daily.last_date("ogd104", "<Error><Code>NoSuchKey</Code></Error>")


def test_a_file_that_stopped_without_a_notice_fails_on_its_age():
    # The three old files as they stood on 24 November 2026.
    today = pd.Timestamp("2026-11-24")
    with pytest.raises(sfoe.SourceStopped, match="57 days old"):
        sfoe.check_source("ogd17", OGD17, sfoe.last_datum(OGD17), today)
    with pytest.raises(sfoe.SourceStopped, match="stopped updating or has moved"):
        sfoe_daily.check("ogd104", OGD104.encode(), today=today)
    with pytest.raises(sfoe.SourceStopped, match="stopped updating or has moved"):
        sfoe_daily.check("ogd35", OGD35.encode(), today=today)


def test_a_fresh_file_passes_up_to_the_limit():
    last = pd.Timestamp("2026-11-16")
    sfoe.check_source("ogd17", OGD17, last, last + pd.Timedelta(days=28))
    with pytest.raises(sfoe.SourceStopped):
        sfoe.check_source("ogd17", OGD17, last, last + pd.Timedelta(days=29))
    assert sfoe_daily.check("ogd104", OGD104.encode(), today=pd.Timestamp("2026-06-28"))
    # September 2026 pumping was published on 6 November 2026
    assert sfoe_daily.check("ogd35", OGD35.encode(), today=pd.Timestamp("2026-11-08"))


def test_a_stopped_file_never_replaces_the_cache(tmp_path, monkeypatch):
    class Response:
        content = (NOTICE + "\n" + OGD35).encode("cp1252")
        headers = {}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(sfoe_daily, "RAW_DIR", tmp_path)
    monkeypatch.setattr(sfoe_daily.requests, "get", lambda *a, **k: Response())
    (tmp_path / "ogd35.csv").write_text("good", encoding="utf-8")
    with pytest.raises(sfoe.SourceStopped):
        sfoe_daily.download("ogd35", refresh=True)
    assert (tmp_path / "ogd35.csv").read_text(encoding="utf-8") == "good"


def test_no_data_address_points_at_the_old_server():
    urls = [config.pipeline()["sfoe"]["csv_url"], *sfoe_daily.URLS.values()]
    assert all(u.startswith("https://www.bfe-ogd.ch/") for u in urls), urls
    for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "config").glob("*.yaml")]:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"https?://\S*uvek-gis\.admin\.ch", text), p.name


@pytest.mark.skipif(
    os.environ.get("ALPINEHYDRO_NETWORK") != "1", reason="set ALPINEHYDRO_NETWORK=1 to download"
)
@pytest.mark.parametrize("name", ["ogd17", "ogd104", "ogd35"])
def test_live_source_is_still_updated_and_carries_no_stop_notice(name):
    url = config.pipeline()["sfoe"]["csv_url"] if name == "ogd17" else sfoe_daily.URLS[name]
    r = requests.get(url, timeout=sfoe.TIMEOUT, headers=sfoe.HEADERS)
    r.raise_for_status()
    if name == "ogd17":
        text = sfoe.decode(r.content)
        sfoe.check_source(name, text, sfoe.last_datum(text), url=url)
    else:
        sfoe_daily.check(name, r.content)
