"""Timing helpers and the timing-ceiling check.

The ceiling asks how much a few days' satellite head start could ever be
worth. A satellite can only add the change in the deviation between the
Sunday reading and the day before release (about 4 days). We take the
standard deviation of the weekly change in the deviation over November to
April, scale it to 4 days in two ways, and multiply by the pre-registered
smallest effect of interest. No price data are used.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

SWISS_AUCTION_CLOCK = pd.Timedelta(hours=11)  # EPEX CH day-ahead gate closure, Europe/Zurich


def first_usable_delivery_day(known_time: pd.Timestamp) -> pd.Timestamp:
    """Delivery day of the first Swiss day-ahead auction held at or after known_time.

    The Swiss auction closes at 11:00 Europe/Zurich for delivery the next day.
    """
    local = known_time.tz_convert("Europe/Zurich")
    day = local.normalize()
    auction = day + SWISS_AUCTION_CLOCK
    if local > auction:
        day = day + pd.Timedelta(days=1)
    return (day + pd.Timedelta(days=1)).tz_localize(None).normalize()


def weekly_deviation_changes(df: pd.DataFrame, dev_col: str, months: list[int]) -> pd.Series:
    """Week-on-week change in a deviation column, for weeks ending in the given months.

    Only pairs exactly 7 days apart are used, so gaps in the data do not
    create long-horizon changes.
    """
    d = df.sort_values("valid_time")[["valid_time", dev_col]].dropna()
    step = d["valid_time"].diff()
    change = d[dev_col].diff()
    keep = (step == pd.Timedelta(days=7)) & d["valid_time"].dt.month.isin(months)
    return change[keep]


@dataclass
class Ceiling:
    dev_col: str
    n_weeks: int
    first_week: str
    last_week: str
    sd_weekly_change_pp: float
    sd_4day_linear_pp: float
    sd_4day_sqrt_pp: float
    ceiling_linear_eur: float
    ceiling_sqrt_eur: float

    def as_dict(self) -> dict:
        return asdict(self)


def timing_ceiling(
    df: pd.DataFrame,
    dev_col: str,
    months: list[int],
    head_start_days: float,
    sesoi_eur_per_10pp: float,
) -> Ceiling:
    d = df.sort_values("valid_time")
    changes = weekly_deviation_changes(d, dev_col, months)
    if changes.size < 2:
        raise ValueError(f"Too few in-season weekly changes of {dev_col} ({changes.size})")
    sd = float(changes.std(ddof=1))
    frac = head_start_days / 7.0
    lin = sd * frac
    sqrt = sd * math.sqrt(frac)
    slope = sesoi_eur_per_10pp / 10.0  # EUR/MWh per point
    weeks = d.loc[changes.index, "valid_time"]
    return Ceiling(
        dev_col=dev_col,
        n_weeks=int(changes.size),
        first_week=weeks.min().strftime("%Y-%m-%d"),
        last_week=weeks.max().strftime("%Y-%m-%d"),
        sd_weekly_change_pp=sd,
        sd_4day_linear_pp=lin,
        sd_4day_sqrt_pp=sqrt,
        ceiling_linear_eur=lin * slope,
        ceiling_sqrt_eur=sqrt * slope,
    )
