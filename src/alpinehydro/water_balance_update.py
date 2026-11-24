"""Water balance 2026, the update to 27 September (post-hoc, plan sections 3, 5 and 7a).

The plan's update window (last Sunday of March to last Sunday of September) is run once
SFOE publishes September 2026 pumping in ogd35. SFOE did so on 6 November 2026 (467 GWh).
This module makes that update, dated 2026-11-24, next to the published result: it writes
its own table and its own results file and changes neither `weekly.csv`,
`monthly_sfoe.csv` nor `water_balance_results.json`.

Two inputs differ from the published run of 22 October 2026:

- P: September 2026 pumping is the published figure, not the 2015 to 2025 mean.
- G: SFOE revised ogd104 Speicherkraft after 22 October, almost only in September 2026
  (deviation V12). The update uses the file as downloaded for the update. The same update
  with G as it stood on 22 October is reported alongside.

Storage and the ENTSO-E columns are copied from the published weekly table.
"""

from __future__ import annotations

import json

import pandas as pd

from alpinehydro import config
from alpinehydro import water_balance as wb

UPDATE_DATE = "2026-11-24"
WEEKLY_UPDATE = wb.OUT_DIR / f"weekly_update_{UPDATE_DATE}.csv"
RESULTS = config.REPORTS / "checks" / f"water_balance_update_{UPDATE_DATE}.json"
REPLACED = ["pumping_gwh", "sfoe_speicherkraft_gwh"]


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#", index_col=0, parse_dates=[0])


def build_table() -> dict:
    """The published weekly table with P and G taken from the cached SFOE files (download
    them first with refresh). Needs no ENTSO-E data and no key."""
    from alpinehydro.fetch import sfoe_daily

    old = _read(wb.WEEKLY)
    new = old.copy()
    monthly = sfoe_daily.monthly_balance()
    pump = sfoe_daily.sfoe_weeks(sfoe_daily.daily_pumping(monthly))
    prod = sfoe_daily.sfoe_weeks(sfoe_daily.daily_storage_production())
    new["pumping_gwh"] = pump["gwh"].reindex(new.index).round(3)
    new["sfoe_speicherkraft_gwh"] = prod["gwh"].reindex(new.index).round(3)
    meta = {n: sfoe_daily.download(n)[1] for n in ("ogd104", "ogd35")}
    header = (
        f"# water balance weekly table, update of {UPDATE_DATE} (post-hoc,"
        " prereg/WATER_BALANCE_PLAN.md)\n"
        f"# {wb.CREDIT}\n"
        "# derived aggregates in GWh only; no raw ENTSO-E data; removed on request\n"
        "# = weekly.csv (published 2026-10-22) with pumping_gwh and sfoe_speicherkraft_gwh\n"
        "# rebuilt from the SFOE files below; every other column is copied unchanged\n"
    )
    for n, m in meta.items():
        header += (
            f"# {n}: {m['url']} downloaded {m['downloaded_utc']},"
            f" Last-Modified {m['http_last_modified']}, sha256 {m['sha256'][:16]}\n"
        )
    out = new.copy()
    out.index = out.index.strftime("%Y-%m-%d")
    WEEKLY_UPDATE.write_text(
        header + out.to_csv(lineterminator="\n"), encoding="utf-8", newline="\n"
    )
    return {"weeks": len(new), "sources": meta}


def changed_weeks(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    """Weeks whose P or G differs between the published table and the update table."""
    out = {}
    for col in REPLACED:
        a, b = old[col], new[col]
        diff = (b - a).where(a.notna() & b.notna())
        filled = b[a.isna() & b.notna()]
        hit = diff[diff.abs() > 0.0005]
        out[col] = {
            "weeks_revised": {str(d.date()): round(float(v), 1) for d, v in hit.items()},
            "weeks_new": {str(d.date()): round(float(v), 1) for d, v in filled.items()},
        }
    return out


def _g_sums(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    col, out = "sfoe_speicherkraft_gwh", {}
    for name, end in (("primary_29_mar_to_30_aug", "aug"), ("update_29_mar_to_27_sep", "sep")):
        a = wb.window_weeks(old, *wb.window(2026, end))[col].sum()
        b = wb.window_weeks(new, *wb.window(2026, end))[col].sum()
        out[name] = {
            "as_of_2026-10-22": round(float(a), 1),
            f"as_of_{UPDATE_DATE}": round(float(b), 1),
            "difference": round(float(b - a), 1),
        }
    return out


def run() -> dict:
    """The update window and the snow link with real September pumping, for G as revised
    and G as of 22 October, and the published provisional figures they replace."""
    old_raw, new_raw = _read(wb.WEEKLY), _read(WEEKLY_UPDATE)
    same = [c for c in old_raw.columns if c not in REPLACED]
    pd.testing.assert_frame_equal(old_raw[same], new_raw[same])
    mixed_raw = old_raw.copy()  # G as of 22 October, P as published by SFOE since
    mixed_raw["pumping_gwh"] = new_raw["pumping_gwh"]
    new, mixed = wb.use_source(new_raw), wb.use_source(mixed_raw)

    published = json.loads(wb.RESULTS.read_text(encoding="utf-8"))
    prov = published["secondary_a_provisional_to_27_september"]
    sep = float(_september_2026(new_raw))
    etas = [str(e) for e in wb.ETAS]

    def both(fn):
        return {
            "g_revised": {e: fn(new, float(e)) for e in etas},
            "g_as_of_2026-10-22": {e: fn(mixed, float(e)) for e in etas},
        }

    out = {
        "post_hoc": True,
        "plan": published["plan"] + ", sections 3 (update window), 5 and 7a",
        "update_date": UPDATE_DATE,
        "updates": "secondary (a) and the snow link of water_balance_results.json;"
        " the primary result and its label are unchanged",
        "g_source": "SFOE ogd104 Speicherkraft (deviation V1), file as revised (deviation V12)",
        "september_2026_pumping_gwh": {
            "sfoe_ogd35_provisional": round(sep, 1),
            "assumed_in_published_a": prov["september_pumping_mean_gwh"],
            "sd_of_assumption": prov["sd_gwh"],
            "sd_above_assumption": round(
                (sep - prov["september_pumping_mean_gwh"]) / prov["sd_gwh"], 2
            ),
        },
        "changed_inputs": changed_weeks(old_raw, new_raw),
        "speicherkraft_2026_window_sums_gwh": _g_sums(old_raw, new_raw),
        "update_window_2026": {
            "published_provisional_a_mean": prov["mean"],
            **both(lambda w, eta: wb.decompose(w, 2026, "sep", eta)),
        },
        "update_window_2022": published["update_window_2022"],
        "snow_link": {
            "published_provisional_mean": published["snow_link_provisional"]["mean"],
            **both(wb.snow_link),
        },
        # Footnote only: the published primary result stands. This is what the revised
        # ogd104 file would give for the same window.
        "primary_window_2026_with_revised_g_footnote": {
            "published": published["primary"]["2026"],
            "g_revised": {e: wb.decompose(new, 2026, "aug", float(e)) for e in etas},
        },
    }
    return out


def _september_2026(table: pd.DataFrame) -> float:
    """September 2026 monthly pumping, recovered from a week that lies wholly in it."""
    return table.loc[pd.Timestamp("2026-09-13"), "pumping_gwh"] / 7 * 30


def write_results(out: dict) -> None:
    RESULTS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
