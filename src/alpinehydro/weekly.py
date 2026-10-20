"""Weekly satellite series aligned to the SFOE week end (Sunday 24:00 Europe/Zurich).

For each SFOE week and reservoir, take the ok scene closest to the week end within
3 days. No interpolation. If there is no ok scene, the closest scene that has a level
(any flag) is kept with its flag as status, so charts can show it as a hollow dot; such
weeks are never used in validation. Energy (GWh) = coefficient (kWh/m3) x
max(V - dead, 0) (Mm3).
"""

from __future__ import annotations

import pandas as pd

from alpinehydro import config, hypsometry, storage

OUT = config.PROCESSED / "satellite" / "weekly.csv"


def week_ends() -> pd.DataFrame:
    """SFOE weeks: valid_time (the Sunday) and the week-end instant in UTC."""
    from alpinehydro.fetch import sfoe

    s = sfoe.load_processed()
    w = s[s["region"] == "TotalCH"][["valid_time", "datum"]].drop_duplicates()
    tz = config.pipeline()["sfoe"]["timezone"]
    w["week_end_utc"] = w["datum"].dt.tz_localize(tz).dt.tz_convert("UTC")
    return w.reset_index(drop=True)


def align(scenes: pd.DataFrame, weeks: pd.DataFrame, max_days: float) -> pd.DataFrame:
    """Closest scene to each week end within max_days, preferring ok scenes."""
    rows = []
    sc = scenes.dropna(subset=["level_m"]).copy()
    sc["time_utc"] = pd.to_datetime(sc["time_utc"], utc=True)
    for w in weeks.itertuples():
        d = (sc["time_utc"] - w.week_end_utc).dt.total_seconds() / 86400
        near = sc[d.abs() <= max_days].assign(days=d[d.abs() <= max_days])
        if near.empty:
            continue
        ok = near[near["flag"] == "ok"]
        pick = (ok if len(ok) else near).loc[lambda x: x["days"].abs().idxmin()]
        rows.append(
            {
                "valid_time": w.valid_time.date(),
                "week_end_utc": w.week_end_utc,
                "scene_time_utc": pick["time_utc"],
                "days_from_week_end": round(float(pick["days"]), 2),
                "sensor": pick["sensor"],
                "scene_id": pick["scene_id"],
                "status": pick["flag"],
                "level_m": pick["level_m"],
                "volume_mm3": pick["volume_mm3"],
                "fill": pick["fill"],
            }
        )
    return pd.DataFrame(rows)


def build(slugs: list[str]) -> pd.DataFrame:
    max_days = config.pipeline()["satellite"]["max_days_from_week_end"]
    scenes = storage.load_scenes()
    weeks = week_ends()
    frames = []
    for slug in slugs:
        r = hypsometry.reservoir(slug)
        a = align(scenes[scenes["reservoir"] == slug], weeks, max_days)
        if a.empty:
            continue
        dead = float(r["gross_volume_mm3"]) - float(r["usable_volume_mm3"])
        a.insert(0, "reservoir", slug)
        a.insert(1, "sfoe_region", r["sfoe_region"])
        a["energy_gwh"] = (
            (a["volume_mm3"] - dead).clip(lower=0) * float(r["energy_kwh_per_m3"])
        ).round(2)
        frames.append(a)
    df = pd.concat(frames, ignore_index=True)
    header = [f"# {line}" for line in storage.credit_lines(df, "scene_time_utc")]
    header += [
        "# One row per reservoir and SFOE week (valid_time = the Sunday, week end = Sunday 24:00"
        " Europe/Zurich).",
        "# The closest ok scene within 3 days of the week end; else the closest scene with a",
        "# level, and status is its flag. Only status 'ok' is used in validation.",
        "# energy_gwh = energy_kwh_per_m3 x max(volume - dead, 0), see config/reservoirs.yaml.",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(header) + "\n" + df.to_csv(index=False, lineterminator="\n")
    OUT.write_bytes(text.encode("utf-8"))
    return df


def load() -> pd.DataFrame:
    df = pd.read_csv(OUT, comment="#", parse_dates=["valid_time"])
    df["scene_time_utc"] = pd.to_datetime(df["scene_time_utc"], utc=True)
    df["week_end_utc"] = pd.to_datetime(df["week_end_utc"], utc=True)
    return df
