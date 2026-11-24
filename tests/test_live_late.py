"""Live check after the failed run of 4 November 2026: sequential CDS downloads, the
ENTSO-E cache rule, forecasts for origins an earlier run missed, and the late note."""

import os

import pandas as pd
import pytest

from alpinehydro import features, live
from alpinehydro.fetch import entsoe, era5

# ---------------------------------------------------------------- CDS queue


class Http(Exception):
    def __init__(self, code, text=""):
        super().__init__(text)
        self.response = type("R", (), {"status_code": code})()


class FakeApi:
    """Each job needs `polls` status checks before it is successful."""

    def __init__(self, clock, polls=2, other_jobs=0):
        self.clock, self.polls, self.other = clock, polls, other_jobs
        self.jobs, self.calls, self.max_in_flight = {}, [], 0
        self.submit_error = self.status_error = None

    def _log(self, what):
        self.calls.append((what, self.clock()))

    def submit(self, request):
        self._log("submit")
        if self.submit_error:
            raise self.submit_error
        running = [u for u, n in self.jobs.items() if n > 0]
        self.max_in_flight = max(self.max_in_flight, len(running) + 1)
        url = f"https://cds.example/jobs/{len(self.jobs)}"
        self.jobs[url] = self.polls
        return url

    def status(self, url):
        self._log("status")
        if self.status_error:
            raise self.status_error
        self.jobs[url] -= 1
        return "successful" if self.jobs[url] <= 0 else "running"

    def download(self, url, path):
        self._log("download")
        path.write_bytes(b"nc")

    def in_flight(self):
        self._log("in_flight")
        self.other -= 1
        return ["someone-else"] if self.other >= 0 else []


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _queue(tmp_path, deadline_min=60, **kw):
    clock = Clock()
    api = FakeApi(clock, **kw)
    q = era5.CdsQueue(api, tmp_path, deadline_min, sleep=clock.sleep, clock=clock)
    return q, api, clock


def _checks(api):
    return [t for what, t in api.calls if what in ("status", "in_flight")]


def test_cds_requests_are_sequential_and_polled_no_faster_than_3_minutes(tmp_path):
    q, api, _ = _queue(tmp_path, deadline_min=600)
    for i in range(3):
        q.fetch({"i": i}, tmp_path / f"f{i}.nc", f"file {i}")
    assert api.max_in_flight == 1
    assert [w for w, _ in api.calls].count("submit") == 3
    t = _checks(api)
    assert min(b - a for a, b in zip(t, t[1:], strict=False)) >= era5.CDS_POLL_SECONDS
    # The first status check of a job comes 3 minutes after its submission, too.
    for i, (what, when) in enumerate(api.calls):
        if what == "submit":
            assert api.calls[i + 1][1] - when >= era5.CDS_POLL_SECONDS
    assert all((tmp_path / f"f{i}.nc").exists() for i in range(3))
    assert not (tmp_path / era5.CDS_INFLIGHT).exists()


def test_cds_waits_while_any_other_request_of_the_account_is_in_flight(tmp_path):
    q, api, _ = _queue(tmp_path, other_jobs=2)
    q.fetch({}, tmp_path / "f.nc", "file")
    kinds = [w for w, _ in api.calls]
    assert kinds.index("submit") == 3  # three idle checks first: busy, busy, free


def test_cds_deadline_leaves_the_job_in_flight_and_the_next_run_resumes_it(tmp_path):
    q, api, clock = _queue(tmp_path, deadline_min=10, polls=50)
    with pytest.raises(era5.CdsDeadline):
        q.fetch({}, tmp_path / "f.nc", "file")
    assert clock() <= 10 * 60  # never waits past the deadline
    assert (tmp_path / era5.CDS_INFLIGHT).exists() and not (tmp_path / "f.nc").exists()
    # Next run: a new queue with the same account state. It must not submit again.
    api.jobs = {u: 2 for u in api.jobs}
    q2 = era5.CdsQueue(api, tmp_path, 60, sleep=clock.sleep, clock=clock)
    before = [w for w, _ in api.calls].count("submit")
    assert q2.resume() == tmp_path / "f.nc"
    assert [w for w, _ in api.calls].count("submit") == before == 1
    assert (tmp_path / "f.nc").exists() and not (tmp_path / era5.CDS_INFLIGHT).exists()


@pytest.mark.parametrize("where", ["submit", "status"])
def test_cds_any_403_stops_everything_until_the_stop_file_is_removed(tmp_path, where):
    q, api, _ = _queue(tmp_path)
    setattr(api, f"{where}_error", Http(403, "forbidden"))
    with pytest.raises(era5.CdsStop):
        q.fetch({}, tmp_path / "f.nc", "file")
    assert (tmp_path / era5.CDS_STOP).exists()
    n = len(api.calls)
    api.submit_error = api.status_error = None
    q2, _, _ = _queue(tmp_path)
    q2._api = api
    with pytest.raises(era5.CdsStop):
        q2.fetch({}, tmp_path / "g.nc", "other")
    with pytest.raises(era5.CdsStop):
        q2.resume()
    assert len(api.calls) == n  # not one more call to the CDS


def test_cds_not_available_yet_is_not_a_failure(tmp_path, monkeypatch):
    q, api, _ = _queue(tmp_path)
    api.submit_error = Http(400, "None of the data you have requested is available yet")
    with pytest.raises(era5.CdsNotAvailable):
        q.fetch({}, tmp_path / "f.nc", "file")
    assert not (tmp_path / era5.CDS_STOP).exists()
    # cds_prefetch turns it into a warning and carries on.
    monkeypatch.setattr(era5, "cds_needs", lambda c, w: [(2026, 12, 2)] if c == "CH" else [])
    monkeypatch.setattr(era5, "CDS_DIR", tmp_path)
    window = live.hdd_window(pd.Timestamp("2026-12-09"))
    warnings = era5.cds_prefetch([window], queue=q, log=lambda m: None)
    assert warnings == ["CDS: CH 2026-12 days 1 to 2 not published yet"]


def _fake_cache(monkeypatch, have):
    """have: {(country, year, month): last day held}."""

    def cached(country, year, month):
        last = have.get((country, year, month), 0)
        idx = pd.date_range(pd.Timestamp(year=year, month=month, day=1), periods=last, freq="D")
        return pd.Series(5.0, index=idx, name="t2m_c")

    monkeypatch.setattr(era5, "_cached_month", cached)


def test_only_the_months_and_days_of_the_hdd_windows_are_requested(monkeypatch):
    ts = pd.Timestamp
    # 4 November 2026: the window of origin day 4 November ends on 28 October. Nothing of
    # November may be asked for (that request was the HTTP 400 of the failed run).
    w1 = live.hdd_window(ts("2026-11-04"))
    assert w1 == (ts("2026-10-01"), ts("2026-10-28"))
    _fake_cache(monkeypatch, {})
    assert era5.cds_needs("CH", [w1]) == [(2026, 10, 28)]
    # A cached month that holds the needed days is reused; a shorter one is not.
    _fake_cache(monkeypatch, {("CH", 2026, 10): 30, ("DE", 2026, 10): 16})
    assert era5.cds_needs("CH", [w1]) == []
    assert era5.cds_needs("DE", [w1]) == [(2026, 10, 28)]
    # Two origins: one request per month, up to the latest day either window needs.
    w2 = live.hdd_window(ts("2026-11-10"))
    assert w2 == (ts("2026-10-07"), ts("2026-11-03"))
    assert era5.cds_needs("DE", [w1, w2]) == [(2026, 10, 31), (2026, 11, 3)]
    assert era5.cds_needs("CH", [w1, w2]) == [(2026, 10, 31), (2026, 11, 3)]
    # First Wednesday of a month, the case that will come back on 2 December 2026.
    _fake_cache(monkeypatch, {})
    assert era5.cds_needs("CH", [live.hdd_window(ts("2026-12-02"))]) == [
        (2026, 10, 31),
        (2026, 11, 25),
    ]


def test_live_hdd_holds_no_day_after_the_window(monkeypatch):
    _fake_cache(monkeypatch, {("CH", 2026, 10): 31, ("CH", 2026, 11): 9})
    hist = pd.Series(1.0, index=pd.date_range("2026-01-01", "2026-11-05", freq="D"))
    start, end = live.hdd_window(pd.Timestamp("2026-11-04"))
    s = era5.hdd_live("CH", start, end, hist=hist)
    assert s.index.max() == end  # nothing published after the origin's own window
    assert (s.loc[start:end] == era5.HDD_BASE_C - 5.0).all() and len(s.loc[start:end]) == 28
    assert (s.loc[:"2026-09-30"] == 1.0).all()  # Earth Engine history before the window month


def test_hdd_window_is_the_one_origin_features_uses():
    """The download window is derived apart from features.py; it must be the same days."""
    od = pd.Timestamp("2026-11-04")
    kt = pd.Timestamp("2026-11-04T21:39:19", tz="Europe/Zurich")
    days = pd.date_range("2026-01-01", "2026-11-12", freq="D")
    hours = pd.date_range("2026-01-01", "2026-11-12", freq="h", tz="Europe/Zurich")
    c = {k: pd.Series(1.0, index=hours) for k in ("fr_nuclear", "ch_nuclear", "de_wind")}
    c["hdd_ch"] = c["hdd_de"] = pd.Series(range(len(days)), index=days, dtype=float)
    start = features.target_start(kt)
    r = pd.DataFrame(
        [
            {
                "valid_time": pd.Timestamp("2026-11-01"),
                "known_time": kt,
                "origin_day": od,
                "target_start": start,
                "target_end": start + pd.Timedelta(days=27),
                "winter": 2026,
                "month": 11,
                "dev_10y_pp": 0.0,
            }
        ]
    )
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    row, _ = features.origin_features(next(r.itertuples()), empty, empty, c)
    w0, w1 = live.hdd_window(od)
    assert row["hdd_ch_last"] == w1 == pd.Timestamp("2026-10-28")
    assert row["hdd_ch"] == c["hdd_ch"].loc[w0:w1].mean() and len(c["hdd_ch"].loc[w0:w1]) == 28
    assert start == pd.Timestamp("2026-11-06")  # known 21:39 -> auction 5 Nov -> delivery 6 Nov


# ---------------------------------------------------------------- ENTSO-E cache


def test_a_month_cached_while_it_was_running_is_fetched_again(tmp_path):
    f = tmp_path / "2026-10.parquet"
    f.write_bytes(b"x")
    end = pd.Timestamp("2026-11-01", tz="Europe/Zurich")
    assert not entsoe.cache_is_final(tmp_path / "missing.parquet", end)
    mid_month = pd.Timestamp("2026-10-21T14:58", tz="UTC").timestamp()
    os.utime(f, (mid_month, mid_month))
    assert not entsoe.cache_is_final(f, end)  # the file behind the 63% wind coverage
    just_after = pd.Timestamp("2026-11-01T12:00", tz="UTC").timestamp()
    os.utime(f, (just_after, just_after))
    assert not entsoe.cache_is_final(f, end)  # under two days after the month ended
    later = pd.Timestamp("2026-11-04T18:09", tz="UTC").timestamp()
    os.utime(f, (later, later))
    assert entsoe.cache_is_final(f, end)


# ---------------------------------------------------------------- origins and the late note


def _storage():
    rows = []
    weeks = ["2026-10-18", "2026-10-25", "2026-11-01", "2026-11-08"]
    for day, gwh in zip(weeks, [6378.0, 6258.0, 6130.0, 5840.0], strict=True):
        vt = pd.Timestamp(day)
        kt = (vt + pd.Timedelta(days=3, hours=21)).tz_localize("Europe/Zurich")
        for region in ("TotalCH", "Wallis"):
            rows.append(
                {
                    "valid_time": vt,
                    "known_time": kt,
                    "region": region,
                    "content_gwh": gwh,
                    "max_gwh": 8895.0,
                    "fill": round(gwh / 8895.0, 6),
                    "source": "pdf",
                }
            )
    return pd.DataFrame(rows)


def test_a_missed_origin_is_still_pending_oldest_first():
    none = pd.DataFrame({"valid_sunday": []})
    got = [str(w["valid_sunday"].date()) for w in live.pending_origins(_storage(), none)]
    assert got == ["2026-11-01", "2026-11-08"]  # October weeks are not live origins
    done = pd.DataFrame({"valid_sunday": ["2026-11-08"]})
    got = [str(w["valid_sunday"].date()) for w in live.pending_origins(_storage(), done)]
    assert got == ["2026-11-01"]  # missed on 4 November, still owed
    both = pd.DataFrame({"valid_sunday": ["2026-11-01", "2026-11-08"]})
    assert live.pending_origins(_storage(), both) == []


def test_weeks_outside_the_live_winter_are_never_origins():
    s = _storage()
    s["valid_time"] = s["valid_time"] + pd.Timedelta(days=364)  # autumn 2027
    assert live.pending_origins(s, pd.DataFrame({"valid_sunday": []})) == []
    assert pd.Timestamp("2026-11-01") == live.LIVE_FIRST
    assert pd.Timestamp("2027-04-30") == live.LIVE_LAST


def test_storage_as_known_puts_back_the_value_first_published():
    s, vs = _storage(), pd.Timestamp("2026-11-01")
    kt = pd.Timestamp("2026-11-04T21:39:19", tz="Europe/Zurich")
    cols = ["logged_utc", "valid_sunday", "region", "old_content_gwh", "old_max_gwh"]
    log = pd.DataFrame(
        [
            # Before known_time: already in the value the forecaster saw. Ignored.
            ["2026-11-04T20:39:19Z", "2026-11-01", "TotalCH", 9999.0, 8895.0],
            # Two later revisions of the week: the value before the first one is restored.
            ["2026-11-17T20:40:00Z", "2026-11-01", "TotalCH", 6125.0, 8895.0],
            ["2026-11-10T20:41:25Z", "2026-11-01", "TotalCH", 6140.0, 8890.0],
            # Other region, other week: ignored.
            ["2026-11-10T20:41:25Z", "2026-11-01", "Wallis", 1.0, 2.0],
            ["2026-11-10T20:41:25Z", "2026-10-25", "TotalCH", 1.0, 2.0],
        ],
        columns=cols,
    )
    d = live.storage_as_known(s, vs, kt, log)
    assert set(d["region"]) == {"TotalCH"} and d["valid_time"].max() == vs  # no later week
    row = d[d["valid_time"] == vs].iloc[0]
    assert (row["content_gwh"], row["max_gwh"]) == (6140.0, 8890.0)
    assert row["fill"] == round(6140.0 / 8890.0, 6)
    assert d.loc[d["valid_time"] == pd.Timestamp("2026-10-25"), "content_gwh"].iloc[0] == 6258.0
    # No revision after known_time: the table's value stands (the case on 2026-11-13).
    same = live.storage_as_known(s, vs, kt, log.iloc[:1])
    assert same.loc[same["valid_time"] == vs, "content_gwh"].iloc[0] == 6130.0
    none = live.storage_as_known(s, vs, kt, pd.DataFrame())
    assert none.loc[none["valid_time"] == vs, "content_gwh"].iloc[0] == 6130.0


def test_late_note_follows_the_start_of_the_target_window():
    start = pd.Timestamp("2026-11-12")  # window of the origin known on 10 Nov 21:41
    on_time = pd.Timestamp("2026-11-11T17:05:00Z")  # the Wednesday run
    assert live.late_note(on_time, start) == ""
    assert live.late_note(pd.Timestamp("2026-11-11T22:59:59Z"), start) == ""  # 23:59:59 Zurich
    note = live.late_note(pd.Timestamp("2026-11-11T23:00:01Z"), start)  # 00:00:01 Zurich
    assert note.startswith("late: made after the target window began on 2026-11-12")
    assert live.late_note(pd.Timestamp("2026-11-13T13:30:00Z"), pd.Timestamp("2026-11-06"))


def test_table_keeps_the_note_and_reads_an_old_file_without_it(tmp_path):
    path = tmp_path / "live.csv"
    row = {c: "" for c in live.COLUMNS}
    rows = [
        {**row, "valid_sunday": "2026-11-01", "note": "late: made after the target window began"},
        {**row, "valid_sunday": "2026-11-08"},
    ]
    live._write(pd.DataFrame(rows), path)
    t = live.load(path)
    assert list(live.is_late(t)) == [True, False] and t["note"].iloc[1] == ""
    assert not live._write(t, path)  # reading and writing back changes nothing
    old = tmp_path / "old.csv"
    cols = [c for c in live.COLUMNS if c != "note"]
    old.write_text(",".join(cols) + "\n" + ",".join("x" for _ in cols) + "\n", encoding="utf-8")
    assert list(live.load(old)["note"]) == [""]


def test_a_csv_week_keeps_the_first_seen_time_of_its_pdf(tmp_path, monkeypatch):
    """After the SFOE address move of 24 November 2026 the CSV replaced seven PDF weeks.
    Their release-log rows are backfilled and hold no time; the week was first seen in
    the PDF, and that time stays its known_time."""
    s = _storage()
    s["source"] = "csv"
    pdf = s[["valid_time", "known_time", "region", "content_gwh", "max_gwh", "fill"]].copy()
    pdf["datum"] = pdf["valid_time"] + pd.Timedelta(days=1)
    pdf["pdf_filename"] = "x.pdf"
    pdf = pdf[pdf["valid_time"] != pd.Timestamp("2026-11-08")]  # 8 Nov: never in a PDF
    body = pdf.assign(known_time=pdf["known_time"].map(lambda t: t.isoformat()))
    body.to_csv(tmp_path / "pdf.csv", index=False)
    rel = tmp_path / "rel.csv"
    rel.write_text(
        "valid_sunday,first_seen_utc,method,http_last_modified\n"
        "2026-10-25,2026-10-27T09:00:00Z,csv_poll,\n"  # CSV seen before the PDF
        "2026-11-01,,backfill_url_move,\n"
        "2026-11-08,,backfill_url_move,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(live, "RELEASE_LOG", rel)
    monkeypatch.setattr(live, "PDF_TABLE", tmp_path / "pdf.csv")
    total = s[s["region"] == "TotalCH"].set_index("valid_time", drop=False)
    w = live._week(total.loc[pd.Timestamp("2026-11-01")], s)
    assert w["first_seen_utc"] == pd.Timestamp("2026-11-04T21:00", tz="Europe/Zurich")
    assert w["source"] == live.PDF_SEEN
    w = live._week(total.loc[pd.Timestamp("2026-10-25")], s)
    assert w["first_seen_utc"] == pd.Timestamp("2026-10-27T09:00:00Z")
    assert w["source"].startswith("SFOE CSV")
    w = live._week(total.loc[pd.Timestamp("2026-11-08")], s)
    assert w["first_seen_utc"] is None  # no time anywhere: the forecast is skipped, not dated
