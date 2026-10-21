import h5py
import numpy as np
import pytest

from alpinehydro.fetch import era5


def test_country_mean_uses_cells_inside_outline_with_area_weights(tmp_path, monkeypatch):
    lat = np.array([47.0, 46.0, 45.0])
    lon = np.array([6.0, 7.0, 8.0])
    t = np.full((2, 3, 3), 300.0)
    t[:, 1, 1] = 280.0  # the only cell (46 N, 7 E) whose centre is inside the outline...
    t[:, 0, 1] = 290.0  # ...together with this one (47 N, 7 E)
    t[1, 0, 1] = np.nan  # missing on day 2: the mean uses the other cell only
    path = tmp_path / "x.nc"
    with h5py.File(path, "w") as h:
        h["latitude"], h["longitude"], h["t2m"] = lat, lon, t
        h["valid_time"] = np.array([0, 1])
        h["valid_time"].attrs["units"] = "days since 2026-10-05 00:00:00"
    box = {
        "type": "Polygon",
        "coordinates": [[[6.5, 45.5], [7.5, 45.5], [7.5, 47.5], [6.5, 47.5], [6.5, 45.5]]],
    }
    monkeypatch.setattr(era5, "outline", lambda c: box)
    s = era5._country_mean(path, "CH")
    w47, w46 = np.cos(np.deg2rad(47)), np.cos(np.deg2rad(46))
    expect = (290 * w47 + 280 * w46) / (w47 + w46) - 273.15
    assert str(s.index[0].date()) == "2026-10-05"
    assert s.iloc[0] == pytest.approx(expect)
    assert s.iloc[1] == pytest.approx(280 - 273.15)
