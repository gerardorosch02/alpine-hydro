"""Country-mean daily 2 m temperature and heating degree days (H1 controls).

ERA5-Land daily aggregates (ECMWF/ERA5_LAND/DAILY_AGGR, band temperature_2m, kelvin) in
Earth Engine. The country mean is area-weighted over the land grid cells inside the
country outline: sum(T x cell area) / sum(cell area), with ee.Image.pixelArea(). ERA5-Land
is land-only, so sea cells are already masked. Outlines: USDOS/LSIB_SIMPLE/2017.

HDD = max(0, 15.5 - T) per day (base 15.5 C, as pre-registered). The series is cached in
data/interim/era5_country/ (git-ignored).

Credit: Contains modified Copernicus Climate Change Service information (ERA5-Land).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alpinehydro import config

OUT_DIR = config.INTERIM / "era5_country"
COUNTRIES = {"CH": "Switzerland", "DE": "Germany"}
HDD_BASE_C = 15.5
SCALE_M = 11132  # ERA5-Land native 0.1 degree


def _year(country: str, year: int) -> pd.Series:
    import ee

    from alpinehydro.earthengine import init

    init()
    ee.data.setWorkloadTag("alpinehydro-weekend3")
    geom = (
        ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017")
        .filter(ee.Filter.eq("country_na", COUNTRIES[country]))
        .geometry()
    )
    end = min(pd.Timestamp(f"{year + 1}-01-01"), pd.Timestamp.today().normalize())
    col = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate(f"{year}-01-01", end.strftime("%Y-%m-%d"))
        .select("temperature_2m")
    )

    def one(img):
        t = img.select("temperature_2m")
        area = ee.Image.pixelArea().updateMask(t.mask())
        s = ee.Image.cat(t.multiply(area).rename("ta"), area.rename("a")).reduceRegion(
            ee.Reducer.sum(), geom, scale=SCALE_M, maxPixels=1e9
        )
        return ee.Feature(
            None, {"t": img.get("system:time_start"), "ta": s.get("ta"), "a": s.get("a")}
        )

    rows = ee.FeatureCollection(col.map(one)).getInfo()["features"]
    df = pd.DataFrame([r["properties"] for r in rows]).dropna()
    day = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    return pd.Series((df["ta"] / df["a"]).to_numpy() - 273.15, index=day, name="t2m_c")


def fetch(country: str, first_year: int = 2004, refresh: bool = False, log=print) -> pd.Series:
    """Daily country-mean temperature (C), cached per year; the current year is refetched."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    this = pd.Timestamp.today().year
    parts = []
    for y in range(first_year, this + 1):
        path = OUT_DIR / f"{country}_{y}.csv"
        if path.exists() and not refresh and y < this:
            s = pd.read_csv(path, parse_dates=["day"]).set_index("day")["t2m_c"]
        else:
            s = _year(country, y).rename_axis("day")
            s.reset_index().to_csv(path, index=False, lineterminator="\n")
            log(f"{country} {y}: {len(s)} days")
        parts.append(s)
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated(keep="first")]


def hdd(country: str) -> pd.Series:
    """Daily heating degree days, base 15.5 C."""
    return (HDD_BASE_C - fetch(country)).clip(lower=0).rename("hdd")


# ---------------------------------------------------------------- CDS route (deviation D15)
#
# How this code talks to the CDS (owner's rules of 2026-11-13, after the run of 4 November
# waited six hours in the CDS queue and ECMWF asked for sequential requests):
# - One request in flight at a time, never two. A request still running when a run ends is
#   written to data/raw/cds/inflight.json and picked up by the next run; nothing new is
#   sent while it, or any other request of the account, is accepted or running.
# - A status check at most once every 3 minutes (CDS_POLL_SECONDS).
# - Any HTTP 403 stops every CDS call and writes data/raw/cds/STOP_403.txt. No request is
#   sent while that file exists; a person checks the account and deletes the file.
# - A run spends at most CDS_DEADLINE_MIN minutes on the CDS (ALPINEHYDRO_CDS_DEADLINE_MIN
#   overrides it for a run by hand). After that the forecast waits for the next run.
# - Only the months an HDD window touches are requested, only up to the window's last day,
#   and a cached month that already holds those days is reused.
# None of this changes which days an HDD window uses: that is fixed in features.py.

CDS_DIR = config.RAW / "cds"
CDS_DATASET = "derived-era5-land-daily-statistics"
BOXES = {"CH": [47.9, 5.9, 45.8, 10.6], "DE": [55.1, 5.8, 47.2, 15.1]}  # N, W, S, E
CDS_POLL_SECONDS = 180
CDS_DEADLINE_MIN = 60
CDS_INFLIGHT = "inflight.json"
CDS_STOP = "STOP_403.txt"


class CdsStop(RuntimeError):
    """HTTP 403 from the CDS, now or in an earlier run: no CDS call is made."""


class CdsDeadline(RuntimeError):
    """The run's time budget for the CDS is used up; a pending request stays in flight."""


class CdsNotAvailable(RuntimeError):
    """The CDS has none of the requested days yet."""


class CdsFailed(RuntimeError):
    """The CDS ended the request without a result."""


def outline(country: str) -> dict:
    """The LSIB_SIMPLE/2017 outline used by the Earth Engine route, cached once as GeoJSON."""
    import json

    path = OUT_DIR / f"{country}_lsib_simple_2017.geojson"
    if not path.exists():
        import ee

        from alpinehydro.earthengine import init

        init()
        geom = (
            ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017")
            .filter(ee.Filter.eq("country_na", COUNTRIES[country]))
            .geometry()
            .getInfo()
        )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(geom), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


class _DatastoresApi:
    """The four CDS calls the queue needs, on the ECMWF client that cdsapi itself wraps.

    The client retries a failed HTTP call at most once, after CDS_POLL_SECONDS.
    """

    def __init__(self):
        import os

        from ecmwf.datastores import Client

        config.secret("CDSAPI_KEY")  # fails without revealing anything if missing
        self.client = Client(
            url=os.environ["CDSAPI_URL"],
            key=os.environ["CDSAPI_KEY"],
            progress=False,
            retry_after=CDS_POLL_SECONDS,
            maximum_tries=2,
        )

    def _kwargs(self) -> dict:
        return self.client._retrieve_api._request_kwargs

    def submit(self, request: dict) -> str:
        """Send one request; returns the URL of its job."""
        return self.client.submit(CDS_DATASET, request).url

    def status(self, url: str) -> str:
        from ecmwf.datastores.processing import Remote

        return Remote(url, **self._kwargs()).status

    def download(self, url: str, path: Path) -> None:
        from ecmwf.datastores.processing import Results

        Results.from_request("get", f"{url}/results", **self._kwargs()).download(str(path))

    def in_flight(self) -> list[str]:
        """IDs of every request of the account that is accepted or running."""
        return self.client.get_jobs(status=["accepted", "running"]).request_ids


def _http_status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


class CdsQueue:
    """Strictly sequential CDS downloads with slow polling, a deadline and a 403 stop."""

    def __init__(self, api=None, state_dir=None, deadline_min=None, sleep=None, clock=None):
        import os
        import time

        self._api = api
        self.dir = Path(state_dir) if state_dir else CDS_DIR
        if deadline_min is None:
            deadline_min = float(os.environ.get("ALPINEHYDRO_CDS_DEADLINE_MIN", CDS_DEADLINE_MIN))
        self.deadline_min = deadline_min
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.deadline = self.clock() + deadline_min * 60
        self.last_check: float | None = None

    @property
    def api(self):
        if self._api is None:
            self._api = _DatastoresApi()
        return self._api

    # -- 403 stop

    def check_stop(self) -> None:
        if (self.dir / CDS_STOP).exists():
            raise CdsStop(
                f"CDS stopped: {self.dir.name}/{CDS_STOP} exists (an HTTP 403 was received);"
                " no CDS request is sent until a person deletes that file"
            )

    def _call(self, fn):
        """Run one CDS call; a 403 writes the stop file and ends all CDS work."""
        self.check_stop()
        try:
            return fn()
        except Exception as exc:
            if _http_status(exc) != 403:
                raise
        import datetime as dt

        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / CDS_STOP).write_text(
            f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}  HTTP 403 from the CDS.\n"
            "No CDS request is sent while this file exists. Check the account at\n"
            "https://cds.climate.copernicus.eu, then delete this file.\n",
            encoding="utf-8",
        )
        raise CdsStop(
            "CDS stopped: HTTP 403 received; no CDS request is sent until a person checks"
            f" the account and deletes {self.dir.name}/{CDS_STOP}"
        )

    # -- pacing

    def _pace(self) -> None:
        """Wait until a status check is allowed (CDS_POLL_SECONDS after the last one)."""
        now = self.clock()
        due = now if self.last_check is None else max(now, self.last_check + CDS_POLL_SECONDS)
        if due > self.deadline:
            raise CdsDeadline(
                f"CDS deadline of {self.deadline_min:g} minutes reached; retried next run"
            )
        if due > now:
            self.sleep(due - now)
        self.last_check = self.clock()

    # -- the request in flight

    def _inflight(self) -> dict | None:
        import json

        path = self.dir / CDS_INFLIGHT
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _set_inflight(self, job: dict | None) -> None:
        import json

        path = self.dir / CDS_INFLIGHT
        if job is None:
            path.unlink(missing_ok=True)
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(job, indent=1), encoding="utf-8")

    def _finish(self, job: dict) -> Path:
        """Poll the job in flight until it ends, then download it to its target."""
        import os

        while True:
            self._pace()
            try:
                status = self._call(lambda: self.api.status(job["url"]))
            except CdsStop:
                raise
            except Exception as exc:
                if _http_status(exc) == 404:  # the CDS no longer knows the job
                    self._set_inflight(None)
                    raise CdsFailed(f"CDS request for {job['label']} no longer exists") from None
                raise
            if status == "successful":
                break
            if status not in ("accepted", "running"):
                self._set_inflight(None)
                raise CdsFailed(f"CDS request for {job['label']} ended as {status!r}")
        target = Path(job["target"])
        part = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._call(lambda: self.api.download(job["url"], part))
        os.replace(part, target)
        self._set_inflight(None)
        return target

    def resume(self) -> Path | None:
        """Finish the request an earlier run left in flight, if there is one."""
        self.check_stop()
        job = self._inflight()
        return self._finish(job) if job else None

    def _wait_until_idle(self) -> None:
        """Wait until the account has no accepted or running request at all."""
        while True:
            self._pace()
            if not self._call(self.api.in_flight):
                return

    def fetch(self, request: dict, target: Path, label: str) -> Path:
        """Download one request to target. Never sends it while another is in flight."""
        import datetime as dt

        self.resume()
        self._wait_until_idle()
        try:
            url = self._call(lambda: self.api.submit(request))
        except CdsStop:
            raise
        except Exception as exc:
            if _http_status(exc) == 400 and "available yet" in str(exc):
                raise CdsNotAvailable(label) from None
            raise
        self.last_check = self.clock()
        job = {
            "url": url,
            "target": str(target),
            "label": label,
            "submitted_utc": f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}",
        }
        self._set_inflight(job)
        return self._finish(job)


_QUEUE: CdsQueue | None = None


def cds_queue() -> CdsQueue:
    """One queue per process, so the deadline covers the whole run."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = CdsQueue()
    return _QUEUE


def _cds_path(country: str, year: int, month: int) -> Path:
    return CDS_DIR / f"{country}_{year}-{month:02d}.nc"


def _cds_request(country: str, year: int, month: int, last_day: int) -> dict:
    return {
        "variable": ["2m_temperature"],
        "year": str(year),
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, last_day + 1)],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": BOXES[country],
    }


def _country_mean(path: Path, country: str) -> pd.Series:
    """Area-weighted mean over land cells whose centre lies inside the outline."""
    import h5py
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import shape

    geom = shape(outline(country))
    with h5py.File(path, "r") as h:
        lat, lon = h["latitude"][:], h["longitude"][:]
        t2m = h["t2m"][:].astype("float64")
        days = h["valid_time"][:]
        units = h["valid_time"].attrs["units"]
    units = units.decode() if isinstance(units, bytes) else units
    base = pd.Timestamp(units.split("since")[1].strip())
    lon2, lat2 = np.meshgrid(lon, lat)
    inside = contains_xy(geom, lon2, lat2)
    w = np.cos(np.deg2rad(lat2)) * inside
    out = {}
    for i, d in enumerate(days):
        v = t2m[i]
        ok = np.isfinite(v) & (w > 0)
        if ok.sum() == 0:
            continue
        out[base + pd.Timedelta(days=float(d))] = float((v[ok] * w[ok]).sum() / w[ok].sum())
    return pd.Series(out, name="t2m_c").sort_index() - 273.15


def _cached_month(country: str, year: int, month: int) -> pd.Series:
    """Country-mean temperature of one cached CDS month (empty if not downloaded)."""
    path = _cds_path(country, year, month)
    if not path.exists():
        return pd.Series(dtype=float, name="t2m_c", index=pd.DatetimeIndex([]))
    return _country_mean(path, country)


def cds_needs(country: str, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> list[tuple]:
    """(year, month, last day) of every month the windows touch whose cached file lacks a
    needed day. One entry per month, with the latest day any window needs in it."""
    need: dict[tuple[int, int], pd.Timestamp] = {}
    for start, end in windows:
        for m in pd.date_range(start.replace(day=1), end, freq="MS"):
            last = min(end, m + pd.offsets.MonthEnd(0))
            need[(m.year, m.month)] = max(need.get((m.year, m.month), last), last)
    out = []
    for (y, m), last in sorted(need.items()):
        have = pd.DatetimeIndex(_cached_month(country, y, m).index).normalize()
        wanted = pd.date_range(pd.Timestamp(year=y, month=m, day=1), last, freq="D")
        if not wanted.isin(have).all():
            out.append((y, m, last.day))
    return out


def cds_prefetch(
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    countries: tuple[str, ...] = ("CH", "DE"),
    queue: CdsQueue | None = None,
    log=print,
) -> list[str]:
    """Download what the HDD windows (first day, last day) still need, one request at a
    time. Returns warnings; a deadline, a 403 stop, a failed request or
    days not published yet end the downloads but never raise: the coverage floor (D9) then
    decides, from the files on disk, which origins can be forecast."""
    warnings: list[str] = []
    try:
        q = queue or cds_queue()
        q.resume()
        # One request per country and month, up to the latest day any window needs, in the
        # order the windows are given: what the oldest origin lacks is downloaded first.
        last = {(c, y, m): d for c in countries for y, m, d in cds_needs(c, windows)}
        order = [(c, y, m) for w in windows for c in countries for y, m, _ in cds_needs(c, [w])]
        tasks = [(y, m, c, last[c, y, m]) for c, y, m in dict.fromkeys(order) if (c, y, m) in last]
        for y, m, c, d in tasks:
            label = f"{c} {y}-{m:02d} days 1 to {d}"
            try:
                q.fetch(_cds_request(c, y, m, d), _cds_path(c, y, m), label)
                log(f"CDS: {label} downloaded")
            except CdsNotAvailable:
                warnings.append(f"CDS: {label} not published yet")
            except CdsFailed as exc:
                warnings.append(str(exc))
    except (CdsDeadline, CdsStop, CdsFailed) as exc:
        warnings.append(str(exc))
    return warnings


def cds_series(country: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Daily country-mean temperature (C) for start..end from the cached CDS months. Days
    that no cached file holds are absent. No network."""
    parts = [
        _cached_month(country, m.year, m.month)
        for m in pd.date_range(start.replace(day=1), end, freq="MS")
    ]
    s = pd.concat(parts).sort_index()
    s.index = pd.DatetimeIndex(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")]
    return s[(s.index >= start) & (s.index <= end)].rename_axis("day")


def hdd_live(
    country: str, start: pd.Timestamp, end: pd.Timestamp, hist: pd.Series | None = None
) -> pd.Series:
    """HDD for one live origin (D15), whose HDD window is start..end: CDS values from the
    first day of the window's first month to `end`, Earth Engine history before that (used
    only for the climatological HDD of past years). Nothing after `end` is included. Reads
    the cached CDS files only; cds_prefetch downloads them."""
    hist = hdd(country) if hist is None else hist
    first = start.replace(day=1)
    cds = (HDD_BASE_C - cds_series(country, first, end)).clip(lower=0)
    return pd.concat([hist[hist.index < first], cds]).sort_index().rename("hdd")
