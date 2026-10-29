# Go-public checklist

Run on 2026-10-22 (weekend 6). The repo is still private. Making it public is the
owner's decision.

| Check | Result |
|---|---|
| History secret scan | Clean |
| History data scan | Clean |
| Personal details | Fixed in HEAD; old paths left in history by the owner's choice |
| Fresh clone, no keys | Pass |
| Notebooks | No notebook was ever committed |
| Licences | ENTSO-E decided 2026-10-22; CDS rechecked 2026-10-29 after the 28 October terms update |

## 1. History secret scan

- gitleaks 8.30.1 (release checksum verified) over every commit on every branch and
  tag: `gitleaks git . --log-opts=--all`. **50 commits scanned, no leaks found.**
- The configured scanner, detect-secrets (pre-commit, `.secrets.baseline`), passed on
  every file changed this weekend.
- Extra check: each real key value from the local `.env` and the Windows environment
  (ENTSO-E token, Earth Engine project, CDS key and URL, Earthdata login) was searched
  for verbatim in every file of every commit and in every commit message. No hits. The
  Earthdata user name appears only as part of the public GitHub handle.

## 2. History data scan

Every path ever committed under `data/`, with its largest version (56 paths, none ever
deleted):

- `data/external/outlines/`: 18 GeoJSON outlines and analysis windows (largest
  294 KB) and a README. Derived from swisstopo open data.
- `data/processed/hypsometry/`: one curve CSV and JSON per reservoir (largest 54 KB).
- `data/processed/satellite/`: `scenes.csv` (630 KB, per-scene levels and flags),
  `weekly.csv` (184 KB), `wallis.csv` (9 KB).
- `data/processed/sfoe_*`: SFOE storage tables and logs (largest 580 KB).
- `data/processed/live_forecasts.csv` (440 bytes, header only).
- `data/processed/snow/`: regional daily means (largest `era5land_swe_daily.csv`,
  3.6 MB, and `modis_daily.csv`, 2.0 MB), feature tables, band polygons, fallback fit,
  glacier share, and `h3b_q4_spread.csv` (450 bytes, 11 yearly means).

None was ever a raw price series, raw imagery or a credential. The column headers of
every table were checked: no price or generation column. (Later, on 2026-10-22, the
post-hoc water balance added weekly and monthly ENTSO-E hydro generation sums in GWh,
`data/processed/water_balance/`, under the ENTSO-E decision in DATA_LICENCES.md. Still no
price column.) No `.parquet`, `.tif`, `.nc`,
`.h5`, `.laz`, `.zip`, `.pdf`, `.ipynb` or `.env` file was ever committed anywhere in
the history. The only blobs over 1 MB are the two snow tables above. `alpinehydro
check-repo` passes on HEAD (168 tracked files).

## 3. Personal details

- Commit authors: `159634061+gerardorosch02@users.noreply.github.com` (98 author and
  committer entries) and `41898282+github-actions[bot]@users.noreply.github.com` (2).
  Both are GitHub noreply addresses.
- Other email addresses in the history: only `t@example.com` in a test fixture.
- Personal paths in HEAD, now fixed:
  - `scripts/weekly.ps1` had the repo path, the uv path and the git path hard-coded.
    It now uses the script's own folder and finds uv and git on PATH, with the
    optional overrides `ALPINEHYDRO_UV` and `ALPINEHYDRO_GIT`. Tested the way the
    scheduled task calls it: it resolved the same uv and git and stopped, as
    designed, at the clean-tree check.
  - `config/pipeline.yaml` had an unused `obsidian_vault` path. Removed.
- **Still in history:** the user name `gerar` in `C:\Users\gerar\...` paths, in older
  versions of `scripts/weekly.ps1` (13 commits) and `config/pipeline.yaml` (50
  commits). It reveals a Windows account name, not a credential. Removing it would need
  a history rewrite, which changes every commit hash and breaks the three tag links.
  **Owner's decision (2026-10-22): leave it.**

## 4. Fresh clone test

In a temporary folder: `git clone` of the local repo (the new commits are not pushed
yet), no `.env`, every key variable removed from the environment, then
`uv sync --locked` and `uv run alpinehydro demo`. **All 15 figures built.** The test
suite also passed there (94 passed, 2 skipped because the H1 feature table needs local
price data). The folder was deleted afterwards. Repeat the test from GitHub after the
push.

The H1 figures and the Dix example scene are not rebuilt by `demo`: they need price
series or imagery, which are never committed.

## 5. Notebooks

No `.ipynb` file was ever committed (`notebooks/` holds only a README). nbstripout runs
in pre-commit for any future notebook.

## 6. Repo settings (for the owner to apply by hand)

- **Description:** Do Swiss hydro storage and Alpine snow predict the Swiss power
  premium? Pre-registered tests on free satellite and public data.
- **Topics:** `energy-trading`, `power-markets`, `hydropower`, `remote-sensing`,
  `google-earth-engine`, `pre-registration`, `switzerland`, `forecasting`.
- **Social preview:** `reports/figures/hero_storage.png` (Settings, General, Social
  preview). GitHub shows it at 2:1, so the lower Valais panel will be cropped.

## Blocking before going public

Nothing. Decided by the owner on 2026-10-22:

- ENTSO-E: keep the derived figures and statistics, credited, with a removal-on-request
  line (DATA_LICENCES.md, "ENTSO-E decision").
- Old paths in history: left as they are.
- Copernicus CDS: rechecked on 2026-10-29 after the 28 October terms update. Both
  ERA5-Land pages are CC BY 4.0; the dataset DOIs were added to the credit line. Nothing
  in the README or desk note implies ECMWF or EU endorsement (Article 5).
