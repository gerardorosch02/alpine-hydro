"""Annual national reservoir inflow from HP-CatCH (ETH Zurich, CC BY 4.0), water balance audit.

HP-CatCH: Haddad et al., linking hydropower infrastructure to their hydrological
catchments in Switzerland, doi:10.3929/ethz-c-000800479. The zip (about 214 MB) is
downloaded by hand to data/raw/hpcatch/ (git-ignored). This reads the zarr store inside
the zip without extracting it, sums `inflows_direct` (m3/s, hourly, PREVAH, each
sub-basin counted once) over all reservoirs, and writes calendar-year volumes in hm3.

Needs numcodecs, which is not a project dependency:
    uv run --with numcodecs python scripts/hpcatch_annual.py data/raw/hpcatch/hp_catch_update1.zip
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from numcodecs import Blosc

STORE = "hp_catch/data/hydropower_inflows/ds_prevah_obs_reservoir_inflows_updated.zarr"
OUT = Path("data/processed/water_balance/hpcatch_annual_inflow.csv")


def read_array(z: zipfile.ZipFile, name: str) -> np.ndarray:
    meta = json.loads(z.read(f"{STORE}/{name}/.zarray"))
    codec = Blosc.from_config({k: v for k, v in meta["compressor"].items() if k != "id"})
    shape, chunks = meta["shape"], meta["chunks"]
    out = np.full(shape, np.nan if meta["dtype"].endswith("f8") else 0, dtype=meta["dtype"])
    n_last = -(-shape[-1] // chunks[-1])
    for j in range(n_last):
        key = f"{STORE}/{name}/" + ("0." if len(shape) == 2 else "") + str(j)
        if key not in z.namelist():
            continue
        block = np.frombuffer(codec.decode(z.read(key)), dtype=meta["dtype"])
        block = block.reshape(chunks)
        sl = slice(j * chunks[-1], min((j + 1) * chunks[-1], shape[-1]))
        width = sl.stop - sl.start
        if len(shape) == 2:
            out[:, sl] = block[:, :width]
        else:
            out[sl] = block[:width]
    return out


def main(zip_path: str) -> None:
    with zipfile.ZipFile(zip_path) as z:
        t = read_array(z, "time")
        q = read_array(z, "inflows_direct")
    time = pd.Timestamp("1991-01-01") + pd.to_timedelta(t, unit="s")
    national = pd.Series(np.nansum(q, axis=0), index=time)
    hours = national.groupby(national.index.year).count()
    hm3 = national.groupby(national.index.year).sum() * 3600 / 1e6
    out = pd.DataFrame(
        {"year": hm3.index, "inflow_hm3": hm3.round(1).to_numpy(), "hours": hours.to_numpy()}
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# source: HP-CatCH, Haddad et al., ETH Zurich, doi:10.3929/ethz-c-000800479, CC BY 4.0\n"
        "# variable: inflows_direct (PREVAH simulated, m3/s hourly), summed over 107 reservoirs\n"
        "# inflow_hm3: calendar-year volume in hm3; hours: hourly values in the year\n"
    )
    OUT.write_text(header + out.to_csv(index=False, lineterminator="\n"), encoding="utf-8")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
