"""Look-ahead checks for the H3 follow-up (post-hoc), plan section 8."""

import pandas as pd
import pytest

from alpinehydro import followup

F = followup.FEATURES


@pytest.fixture(scope="module")
def f():
    if not F.exists():
        pytest.skip("follow-up features not built")
    return pd.read_csv(F, comment="#")


def test_era5_days_end_at_or_before_issue_minus_7(f):
    u = f[f["issue"].isin(followup.UPDATES)].dropna(subset=["era5_last"])
    assert len(u) > 0
    last = pd.to_datetime(u["era5_last"])
    issue = pd.to_datetime(u["issue_date"])
    assert (last <= pd.to_datetime(u["era5_cutoff"])).all()
    assert (last <= issue - pd.Timedelta(days=7)).all()


def test_modis_2500_days_end_at_or_before_issue_minus_3(f):
    a = f[f["issue"] == "apr1_2500"].dropna(subset=["modis_last"])
    assert len(a) > 0
    last = pd.to_datetime(a["modis_last"])
    assert (last <= pd.to_datetime(a["issue_date"]) - pd.Timedelta(days=3)).all()


def test_storage_was_known_at_the_issue_date(f):
    k = pd.to_datetime(f["start_known_time"], utc=True)
    limit = (
        (pd.to_datetime(f["issue_date"]) + pd.Timedelta(hours=23, minutes=59))
        .dt.tz_localize("Europe/Zurich")
        .dt.tz_convert("UTC")
    )
    ok = k.notna()
    assert ok.sum() > 0
    assert (k[ok] <= limit[ok]).all()


def test_update_snow_is_the_1_may_feature_only(f):
    """Updates reuse the 1 May FSC; no snow data after 28 April enters them."""
    from alpinehydro import features_snow

    h3 = features_snow.load()
    may = h3[(h3["issue"] == "may1") & (h3["band_m"] == 1800)][["year", "region", "modis_fsc"]]
    u = f[f["issue"] == "jul1"].merge(may, on=["year", "region"])
    assert u["snow"].round(4).equals(u["modis_fsc"].round(4))
