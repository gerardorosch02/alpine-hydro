"""Point-in-time feature table for H1 (and H2), timed exactly as pre-registered.

One origin per SFOE weekly reading whose valid Sunday falls in November to April.

- known_time: Thursday 23:59 Europe/Zurich after the valid Sunday (historical rule).
- origin day: the Europe/Zurich date of known_time.
- target window: the 28 delivery days starting with the delivery day of the first Swiss
  day-ahead auction after known_time (auction 11:00 Europe/Zurich for the next day).
- y: mean daily CH minus DE-LU baseload spread over the window (DE-AT-LU before
  2018-10-01, handled in fetch/entsoe.py). Daily baseload = mean of the delivery-day hours.
- x: dev_10y_pp.
- Controls (primary): French nuclear and German wind (onshore + offshore) over the 28 days
  ending the day before the origin day; Swiss nuclear and CH and DE HDD over the 28 days
  ending 7 days before the origin day; climatological HDD of the target window from the
  10 most recent past years; month dummies.
- Realised-controls variant (explanatory, not a forecast): every control over the target
  window, with realised HDD replacing the climatological HDD.

Every input carries its latest date (`*_last`), so tests can check the timing. The table
holds price-derived numbers and stays in data/interim/ (git-ignored).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alpinehydro import config

TZ = "Europe/Zurich"
AUCTION_HOUR = 11  # Swiss day-ahead auction closes 11:00 Europe/Zurich for the next day
WINDOW_DAYS = 28
LAG_DAYS = 7  # Swiss nuclear and HDD windows end 7 days before the origin day
SEASON_MONTHS = (11, 12, 1, 2, 3, 4)
OUT = config.INTERIM / "features_h1.parquet"
OUT_REALISED = config.INTERIM / "features_h1_realised.parquet"


def target_start(known_time: pd.Timestamp) -> pd.Timestamp:
    """Delivery day of the first Swiss auction held after known_time (a naive date)."""
    local = known_time.tz_convert(TZ)
    day = local.normalize().tz_localize(None)
    auction_day = day if local.hour < AUCTION_HOUR else day + pd.Timedelta(days=1)
    return auction_day + pd.Timedelta(days=1)


def origins(storage: pd.DataFrame) -> pd.DataFrame:
    from alpinehydro.norms import add_norms

    d = add_norms(storage[storage["region"] == "TotalCH"], windows=(10,))
    d = d[d["valid_time"].dt.month.isin(SEASON_MONTHS)].copy()
    d["origin_day"] = d["known_time"].dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
    d["target_start"] = [target_start(k) for k in d["known_time"]]
    d["target_end"] = d["target_start"] + pd.Timedelta(days=WINDOW_DAYS - 1)
    # Winter label by its start year: November 2021 to April 2022 is 2021.
    vt = d["valid_time"]
    d["winter"] = vt.dt.year - (vt.dt.month <= 4).astype(int)
    d["month"] = vt.dt.month
    cols = ["valid_time", "known_time", "origin_day", "target_start", "target_end", "winter"]
    return d[cols + ["month", "dev_10y_pp"]].reset_index(drop=True)


def _window_mean(daily: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> tuple[float, int]:
    """Mean over [start, end] (inclusive days) and the number of days with data."""
    w = daily.loc[start:end].dropna()
    return (float(w.mean()) if len(w) else np.nan), int(len(w))


def daily_spread(a: str = "CH", b: str = "DE_LU") -> pd.Series:
    """Daily baseload spread a minus b, only on days where both are complete."""
    d = pd.read_parquet(config.INTERIM / "entsoe_prices_daily.parquet")
    d = d[d["complete"]]
    p = d.pivot(index="valid_time", columns="zone", values="baseload")
    return (p[a] - p[b]).dropna().rename(f"{a}-{b}")


def daily_controls() -> dict[str, pd.Series]:
    from alpinehydro.fetch import entsoe, era5

    gen = {n: entsoe.generation_hourly(n) for n in entsoe.GENERATION}
    # German wind counts an hour only when both onshore and offshore have it.
    wind = (gen["de_wind_onshore"] + gen["de_wind_offshore"]).dropna()
    return {
        "fr_nuclear": gen["fr_nuclear"],
        "ch_nuclear": gen["ch_nuclear"],
        "de_wind": wind,
        "hdd_ch": era5.hdd("CH"),
        "hdd_de": era5.hdd("DE"),
    }


HOURLY = ("fr_nuclear", "ch_nuclear", "de_wind")
MIN_COVERAGE = 0.90  # deviation D9: below this share of expected hours (or days), missing


def control_window(
    series: pd.Series, name: str, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[float, float]:
    """Mean over the days start..end (inclusive) and the share of expected data present.

    Generation controls (hourly, Europe/Zurich index): the mean MW over every available
    hour, so a partial day counts with the hours it has; coverage is hours present over the
    hours of those local days. HDD (daily): mean over available days; coverage is days present
    over 28. Below MIN_COVERAGE the control is set to missing (deviation D9).
    """
    if name in HOURLY:
        lo = pd.Timestamp(start.date(), tz=TZ)
        hi = pd.Timestamp((end + pd.Timedelta(days=1)).date(), tz=TZ)
        w = series[(series.index >= lo) & (series.index < hi)]
        expected = (hi - lo) / pd.Timedelta(hours=1)
    else:
        w = series.loc[start:end].dropna()
        expected = (end - start).days + 1
    cov = len(w) / expected
    value = float(w.mean()) if len(w) and cov >= MIN_COVERAGE else np.nan
    return value, round(float(cov), 4)


def climatological_hdd(hdd: pd.Series, start: pd.Timestamp, origin_day: pd.Timestamp) -> float:
    """Mean over the 28 target days of the same-calendar-day HDD in the 10 most recent
    years in which that calendar day falls before the origin day (29 Feb uses 28 Feb)."""
    vals = []
    for d in pd.date_range(start, periods=WINDOW_DAYS):
        m, dd = (2, 28) if (d.month, d.day) == (2, 29) else (d.month, d.day)
        past = []
        y = d.year
        while len(past) < 10 and y > d.year - 40:
            day = pd.Timestamp(year=y, month=m, day=dd)
            if day < origin_day and day in hdd.index:
                past.append(hdd.loc[day])
            y -= 1
        vals.append(np.mean(past) if len(past) == 10 else np.nan)
    return float(np.mean(vals))


def build(write: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Primary (point-in-time) and realised-controls feature tables."""
    from alpinehydro.fetch import sfoe

    o = origins(sfoe.load_processed())
    spread = daily_spread("CH", "DE_LU")
    spread_it = daily_spread("CH", "IT_NORD")
    c = daily_controls()
    one = pd.Timedelta(days=1)
    rows, real = [], []
    for r in o.itertuples():
        od = r.origin_day
        row = r._asdict()
        row.pop("Index")
        y, ny = _window_mean(spread, r.target_start, r.target_end)
        y2, ny2 = _window_mean(spread_it, r.target_start, r.target_end)
        row.update(y=y, y_days=ny, y_it=y2, y_it_days=ny2)
        # B1 input: the 28 delivery days ending the day before the origin day (deviation
        # D6 of 2026-10-21, the conservative reading of "the 28 days before the origin").
        last, nl = _window_mean(spread, od - WINDOW_DAYS * one, od - one)
        row.update(last28=last, last28_days=nl, last28_last=od - one)
        # Controls, primary timing.
        e1 = od - one
        for k in ("fr_nuclear", "de_wind"):
            v, cov = control_window(c[k], k, e1 - (WINDOW_DAYS - 1) * one, e1)
            row.update({k: v, f"{k}_cov": cov, f"{k}_last": e1})
        e7 = od - LAG_DAYS * one
        for k in ("ch_nuclear", "hdd_ch", "hdd_de"):
            v, cov = control_window(c[k], k, e7 - (WINDOW_DAYS - 1) * one, e7)
            row.update({k: v, f"{k}_cov": cov, f"{k}_last": e7})
        for k in ("hdd_ch", "hdd_de"):
            row[f"clim_{k}"] = climatological_hdd(c[k], r.target_start, od)
        rows.append(row)
        # Realised-controls variant: every control over the target window.
        rr = {k: row[k] for k in ("valid_time", "known_time", "origin_day", "target_start")}
        rr.update({k: row[k] for k in ("target_end", "winter", "month", "dev_10y_pp", "y")})
        rr.update({k: row[k] for k in ("y_days", "y_it", "y_it_days", "last28")})
        for k in ("fr_nuclear", "de_wind", "ch_nuclear", "hdd_ch", "hdd_de"):
            v, cov = control_window(c[k], k, r.target_start, r.target_end)
            rr.update({k: v, f"{k}_cov": cov})
        real.append(rr)
    f, fr = pd.DataFrame(rows), pd.DataFrame(real)
    if write:
        config.INTERIM.mkdir(parents=True, exist_ok=True)
        f.to_parquet(OUT)
        fr.to_parquet(OUT_REALISED)
    return f, fr


def load(realised: bool = False) -> pd.DataFrame:
    return pd.read_parquet(OUT_REALISED if realised else OUT)
