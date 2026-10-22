"""ENTSO-E day-ahead prices and the Swiss reservoir series.

Licence: day-ahead prices (Transparency Regulation article 12.1.d) and
reservoir filling (16.1.d) are not on ENTSO-E's list of data for free re-use
(CC-BY 4.0, list of 18 October 2023). Nothing fetched here is ever committed.
Raw monthly caches go to data/raw/entsoe/ and derived tables to
data/interim/, both git-ignored.

Resolution: since 2025-10-01 the coupled zones clear in 15-minute steps while
CH stays hourly. Every series is averaged into hourly bins. The bins are
built on the UTC axis, which is safe because Europe/Zurich is always a whole
number of hours from UTC, and then converted to Europe/Zurich. Local days
therefore have 23 hours in March and 25 in October, and every daily and
weekly mean is taken over the hours that actually exist in that local period.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pandas as pd

from alpinehydro import config

TZ = "Europe/Zurich"
PRICE_DIR = config.RAW / "entsoe" / "prices"
RES_DIR = config.RAW / "entsoe" / "reservoir"


def redact(text: str) -> str:
    """Remove the API token from text (requests puts the full URL in HTTP errors)."""
    return re.sub(r"securityToken=[^&\s'\"]+", "securityToken=REDACTED", text)


class _SafeClient:
    """Wraps EntsoePandasClient so no error message or traceback can carry the key.

    NoMatchingDataError passes through unchanged (callers catch it; it holds no URL).
    Any other error is re-raised as RuntimeError with the token removed and the
    original exception dropped from the chain, so it is never printed.
    """

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        method = getattr(self._client, name)

        def call(*args, **kwargs):
            from entsoe.exceptions import NoMatchingDataError

            try:
                return method(*args, **kwargs)
            except NoMatchingDataError:
                raise
            except Exception as e:
                msg = f"{type(e).__name__}: {redact(str(e))}"
            raise RuntimeError(msg)

        return call


def _client():
    from entsoe import EntsoePandasClient

    return _SafeClient(EntsoePandasClient(api_key=config.secret("ENTSOE_API_KEY")))


def area_for(zone: str, month_start: pd.Timestamp) -> str:
    """ENTSO-E area code for a zone in a given month (DE_AT_LU before the split)."""
    split = pd.Timestamp(config.pipeline()["entsoe"]["de_split_date"], tz=TZ)
    if zone == "DE_LU" and month_start < split:
        return "DE_AT_LU"
    return zone


def months(start: str, end: pd.Timestamp | None = None) -> list[pd.Timestamp]:
    end = end or pd.Timestamp.now(tz=TZ)
    first = pd.Timestamp(start, tz=TZ).replace(day=1)
    return list(pd.date_range(first, end, freq="MS", tz=TZ))


def _month_is_final(month_start: pd.Timestamp) -> bool:
    """A month is final once its last delivery day is two days in the past."""
    month_end = month_start + pd.offsets.MonthBegin(1)
    return month_end <= pd.Timestamp.now(tz=TZ) - pd.Timedelta(days=2)


def fetch_month(client, zone: str, month_start: pd.Timestamp, refresh: bool = False) -> pd.Series:
    """Fetch one month of prices at native resolution, cached as parquet in UTC."""
    path = PRICE_DIR / zone / f"{month_start:%Y-%m}.parquet"
    if path.exists() and not refresh and _month_is_final(month_start):
        return pd.read_parquet(path)["price"]
    from entsoe.exceptions import NoMatchingDataError

    end = month_start + pd.offsets.MonthBegin(1)
    area = area_for(zone, month_start)
    try:
        s = client.query_day_ahead_prices(area, start=month_start, end=end)
    except NoMatchingDataError:
        s = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    # entsoe-py returns a full index with NaN where ENTSO-E has no value; drop those.
    s = s.dropna().tz_convert("UTC")
    s = s[(s.index >= month_start.tz_convert("UTC")) & (s.index < end.tz_convert("UTC"))]
    s = s[~s.index.duplicated(keep="first")].sort_index()
    df = pd.DataFrame({"price": s.astype(float), "area": area})
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df["price"]


def fetch_prices(zones: list[str] | None = None, refresh: bool = False, log=print) -> None:
    cfg = config.pipeline()["entsoe"]
    zones = zones or cfg["zones"]
    client = _client()
    for zone in zones:
        for m in months(cfg["start"]):
            s = fetch_month(client, zone, m, refresh=refresh)
            log(f"{zone} {m:%Y-%m}: {len(s)} values")


def load_raw(zone: str) -> pd.Series:
    files = sorted((PRICE_DIR / zone).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No cached prices for {zone}. Run: alpinehydro fetch-entsoe")
    parts = [pd.read_parquet(f)["price"] for f in files]
    s = pd.concat([p for p in parts if len(p)]).sort_index()
    return s[~s.index.duplicated(keep="first")]


# ---------------------------------------------------------------- resampling


def to_hourly(s: pd.Series) -> pd.DataFrame:
    """Hourly mean of a tz-aware series of any resolution, indexed in Europe/Zurich.

    n_values counts the source values in each hour (1 for hourly, 4 for 15-minute).
    """
    utc = s.tz_convert("UTC")
    g = utc.resample("1h")
    out = pd.DataFrame({"price": g.mean(), "n_values": g.count()})
    out = out[out["n_values"] > 0]
    out.index = out.index.tz_convert(TZ)
    out.index.name = "hour_start"
    return out


def hours_in_local_day(day: pd.Timestamp) -> int:
    start = pd.Timestamp(day.date(), tz=TZ)
    end = pd.Timestamp((day + pd.Timedelta(days=1)).date(), tz=TZ)
    return int((end - start) / pd.Timedelta(hours=1))


def daily_baseload(hourly: pd.DataFrame, known_clock: str = "13:00") -> pd.DataFrame:
    """Mean over the hours of each Europe/Zurich delivery day.

    valid_time is the delivery day. known_time is a conservative D-1 at
    known_clock Europe/Zurich, when the day-ahead results are public.
    """
    local_day = hourly.index.tz_localize(None).normalize()
    g = hourly["price"].groupby(local_day)
    out = pd.DataFrame({"baseload": g.mean(), "n_hours": g.count()})
    out.index.name = "valid_time"
    out["expected_hours"] = [hours_in_local_day(d) for d in out.index]
    out["complete"] = out["n_hours"] == out["expected_hours"]
    hh, mm = (int(x) for x in known_clock.split(":"))
    kt = (out.index - pd.Timedelta(days=1)) + pd.Timedelta(hours=hh, minutes=mm)
    out["known_time"] = kt.tz_localize(TZ)
    return out.reset_index()


def weekly_baseload(hourly: pd.DataFrame) -> pd.DataFrame:
    """Mean over the hours of each ISO week (Monday to Sunday, Europe/Zurich)."""
    naive = hourly.index.tz_localize(None)
    week_start = naive.normalize() - pd.to_timedelta(naive.dayofweek, unit="D")
    g = hourly["price"].groupby(week_start)
    out = pd.DataFrame({"baseload": g.mean(), "n_hours": g.count()})
    out.index.name = "week_start"
    expected = []
    for ws in out.index:
        expected.append(sum(hours_in_local_day(ws + pd.Timedelta(days=i)) for i in range(7)))
    out["expected_hours"] = expected
    out["complete"] = out["n_hours"] == out["expected_hours"]
    out["valid_time"] = out.index + pd.Timedelta(days=6)  # the Sunday that ends the week
    return out.reset_index()


def build_tables(zones: list[str] | None = None) -> dict[str, int]:
    """Build hourly, daily and weekly baseload tables in data/interim/ (git-ignored)."""
    cfg = config.pipeline()["entsoe"]
    zones = zones or cfg["zones"]
    hourly_parts, daily_parts, weekly_parts = [], [], []
    for zone in zones:
        h = to_hourly(load_raw(zone))
        d = daily_baseload(h, cfg["price_known_clock"])
        w = weekly_baseload(h)
        for part, lst in ((h.reset_index(), hourly_parts), (d, daily_parts), (w, weekly_parts)):
            part.insert(0, "zone", zone)
            lst.append(part)
    config.INTERIM.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, parts in (("hourly", hourly_parts), ("daily", daily_parts), ("weekly", weekly_parts)):
        df = pd.concat(parts, ignore_index=True)
        df.to_parquet(config.INTERIM / f"entsoe_prices_{name}.parquet")
        counts[name] = len(df)
    return counts


# ---------------------------------------------------------------- reservoir series


def fetch_reservoir(zone: str = "CH", first_year: int = 2014, refresh: bool = False) -> pd.Series:
    """Weekly aggregate reservoir filling in MWh, cached per year in data/raw/."""
    from entsoe.exceptions import NoMatchingDataError

    client = _client()
    parts = []
    this_year = datetime.now(UTC).year
    for year in range(first_year, this_year + 1):
        path = RES_DIR / f"{zone}_{year}.parquet"
        if path.exists() and not refresh and year < this_year:
            parts.append(pd.read_parquet(path)["mwh"])
            continue
        start = pd.Timestamp(f"{year}-01-01", tz=TZ)
        end = min(pd.Timestamp(f"{year + 1}-01-01", tz=TZ), pd.Timestamp.now(tz=TZ))
        try:
            r = client.query_aggregate_water_reservoirs_and_hydro_storage(
                zone, start=start, end=end
            )
            s = r.iloc[:, 0] if isinstance(r, pd.DataFrame) else r
        except NoMatchingDataError:
            s = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        s = s.tz_convert("UTC").astype(float).rename("mwh")
        path.parent.mkdir(parents=True, exist_ok=True)
        s.to_frame().to_parquet(path)
        parts.append(s)
    s = pd.concat([p for p in parts if len(p)]).sort_index()
    return s[~s.index.duplicated(keep="first")]


def compare_reservoir_with_sfoe(entsoe_mwh: pd.Series, sfoe_total: pd.DataFrame) -> dict:
    """Match ENTSO-E weekly CH storage to SFOE TotalCH by the nearest Monday.

    ENTSO-E stamps are around Sunday/Monday midnight local time, so each is
    rounded to the nearest local midnight and compared with SFOE's Datum.
    """
    local = entsoe_mwh.index.tz_convert(TZ).tz_localize(None).round("D")
    e = pd.Series(entsoe_mwh.to_numpy() / 1000.0, index=local, name="entsoe_gwh")
    e = e[~e.index.duplicated(keep="first")]  # yearly query chunks overlap at New Year
    s = sfoe_total.set_index("datum")["content_gwh"]
    out = {
        "entsoe_first": str(e.index.min().date()),
        "entsoe_last": str(e.index.max().date()),
        "entsoe_weeks": int(e.size),
    }
    best = None
    for lag_weeks in (-1, 0, 1):
        j = pd.concat([e.shift(lag_weeks, freq="7D"), s], axis=1, join="inner").dropna()
        diff = (j["entsoe_gwh"] - j["content_gwh"]).abs()
        stats = {
            "lag_weeks": lag_weeks,
            "n": int(len(j)),
            "mean_abs_diff_gwh": float(diff.mean()),
            "share_within_1gwh": float((diff <= 1.0).mean()),
            "max_abs_diff_gwh": float(diff.max()),
        }
        if best is None or stats["mean_abs_diff_gwh"] < best["mean_abs_diff_gwh"]:
            best, best_j = stats, j
    out.update(best)
    diff = (best_j["entsoe_gwh"] - best_j["content_gwh"]).abs()
    by_year = diff.groupby(diff.index.year).agg(["mean", lambda x: (x <= 1.0).mean()])
    by_year.columns = ["mean_abs_diff_gwh", "share_within_1gwh"]
    out["by_year"] = {
        int(k): {c: round(float(v), 3) for c, v in row.items()} for k, row in by_year.iterrows()
    }
    return out


# ---------------------------------------------------------------- generation (H1 controls)

GEN_DIR = config.RAW / "entsoe" / "generation"
# Pre-registered controls: (area, production type). Onshore wind must be fetched by month
# (year-long requests fail for some years, weekend 1); the others are fetched by year and
# fall back to months if a year fails.
GENERATION = {
    "fr_nuclear": ("FR", "B14", "year"),
    "ch_nuclear": ("CH", "B14", "year"),
    "de_wind_offshore": ("DE", "B18", "year"),
    "de_wind_onshore": ("DE", "B19", "month"),
}


def _generation_query(client, area: str, psr: str, start: pd.Timestamp, end: pd.Timestamp):
    from entsoe.exceptions import NoMatchingDataError

    try:
        g = client.query_generation(area, start=start, end=end, psr_type=psr)
    except NoMatchingDataError:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    if isinstance(g, pd.DataFrame):
        if isinstance(g.columns, pd.MultiIndex):
            # (type, "Actual Aggregated" / "Actual Consumption"): keep generation only.
            keep = [c for c in g.columns if c[-1] == "Actual Aggregated"]
            g = g[keep] if keep else g
        g = g.iloc[:, 0]
    g = g.dropna().tz_convert("UTC")
    g = g[(g.index >= start.tz_convert("UTC")) & (g.index < end.tz_convert("UTC"))]
    return g[~g.index.duplicated(keep="first")].sort_index().astype(float)


def _retry(fn, attempts: int = 4, wait_s: float = 20.0):
    """Retry transient ENTSO-E failures (HTTP 599 and similar), waiting longer each time."""
    import time

    for i in range(attempts):
        try:
            return fn()
        except RuntimeError:
            if i == attempts - 1:
                raise
            time.sleep(wait_s * (i + 1))


def fetch_generation(name: str, first: str = "2015-01-01", refresh: bool = False, log=print):
    """Cache one pre-registered generation series (native resolution, MW) by period."""
    area, psr, step = GENERATION[name]
    client = _client()
    now = pd.Timestamp.now(tz=TZ)
    yearly = list(pd.date_range(pd.Timestamp(first, tz=TZ), now, freq="YS"))
    starts = yearly if step == "year" else months(first)
    for s in starts:
        end = s + (pd.offsets.YearBegin(1) if step == "year" else pd.offsets.MonthBegin(1))
        path = GEN_DIR / name / f"{s:%Y-%m}.parquet"
        final = end <= now - pd.Timedelta(days=2)
        if path.exists() and not refresh and final:
            continue
        try:
            g = _retry(lambda s=s, end=end: _generation_query(client, area, psr, s, min(end, now)))
        except Exception as e:  # a failing year is fetched month by month instead
            if step != "year":
                raise
            log(f"{name} {s:%Y}: year request failed ({type(e).__name__}), fetching by month")
            g = pd.concat(
                [
                    _retry(
                        lambda m=m: _generation_query(
                            client, area, psr, m, min(m + pd.offsets.MonthBegin(1), now)
                        )
                    )
                    for m in pd.date_range(s, min(end, now), freq="MS", inclusive="left")
                ]
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"mw": g}).to_parquet(path)
        log(f"{name} {s:%Y-%m}: {len(g)} values")


def generation_hourly(name: str) -> pd.Series:
    """Hourly mean MW (UTC bins, indexed in Europe/Zurich). Hours without data are absent.

    15-minute values are averaged, never summed.
    """
    files = sorted((GEN_DIR / name).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No cached generation for {name}")
    s = pd.concat([pd.read_parquet(f)["mw"] for f in files]).sort_index()
    s = s[~s.index.duplicated(keep="first")]
    h = s.resample("1h").mean().dropna()
    h.index = h.index.tz_convert(TZ)
    return h.rename(name)
