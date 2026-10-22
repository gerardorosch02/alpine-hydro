# alpine-hydro

[![CI](https://github.com/gerardorosch02/alpine-hydro/actions/workflows/ci.yml/badge.svg)](https://github.com/gerardorosch02/alpine-hydro/actions/workflows/ci.yml)

Swiss hydro reservoirs hold about 8.9 TWh, and how full they are drives the Swiss power
premium. This project tests, with plans frozen in git before each fit, whether free
data (satellite lakes, weekly federal storage, satellite snow) give an edge on that
premium. **Storage does line up
with the Swiss minus German day-ahead spread, about EUR 7.7/MWh more per 10 points of
storage shortfall, but most of that comes from the 2021/22 and 2022/23 crisis winters,
and it does not beat a forecast from controls alone out of sample.** Snow cover does
not add skill to the refill forecast either. For a desk, the storage signal is real in
stress winters, but in these data it did not give a tradable forecast edge.

![Swiss hydro storage against its 2000 to 2025 range, and Valais against the satellite check](reports/figures/hero_storage.png)

*As of the SFOE week ending Sunday 18 October 2026: 71.7% full, 12.6 points below the
10-year norm. A GitHub Action redraws the chart each new SFOE week.*

## What I found

| Question | Result | In plain words |
|---|---|---|
| Can free satellites track Alpine storage? | Wallis R² 0.695 (n 46); 0.408 without 2026 | Yes in big summer refill years, no near full or in winter. |
| Is a few days' satellite head start worth anything? | EUR 0.17 to 0.23/MWh | No. |
| Does storage predict the CH minus DE-LU spread (H1)? | Slope −7.72 per 10 points; Clark-West p 0.030; out-of-sample R² vs controls 0.009 | No edge. The link is real but driven by the crisis winters. |
| Does 1 May snow forecast the refill (H3a)? | Skill +0.175 vs storage alone; Holm p 0.268 | No added skill. |
| Does a summer update fix it (post-hoc)? | 1 July skill +0.012; Holm p 0.241 | No. |

All numbers, with every test: [reports/results.md](reports/results.md). For a trader's
one-page reading: [docs/DESK_NOTE.md](docs/DESK_NOTE.md).

### Water balance 2026 (post-hoc)

![2026 water balance against 2015 to 2025](reports/figures/water_balance_2026.png)

**Label: weather story.** From April to August 2026 less water reached Swiss reservoirs
than in any year since 2015, about 2,600 GWh below the 2015 to 2025 mean, and operators
released about 2,300 GWh less, not more. The 1 May snow forecast missed the water, not the
operators. A post-hoc diagnostic with its own plan tag,
[v0.4-waterbalance-plan](https://github.com/gerardorosch02/alpine-hydro/tree/v0.4-waterbalance-plan).

## How it works

**A. Satellite lakes.** Sentinel-2 and Landsat water masks are matched to
level-volume curves from swisstopo terrain, turned into energy, and checked on three
Valais lakes against the weekly numbers of the Swiss Federal Office of Energy (SFOE).

**B. Storage and the Swiss premium.** SFOE fill minus its 10-year norm, as known on
release day, against the next 28-day CH minus DE-LU spread (November to April, 11
winters, 5 tested). It must beat controls alone (nuclear, wind, heating degree days).

**C. Snow and refill.** MODIS snow cover above 1800 m on 1 May, against how full the
Alpine regions are at the end of September, beyond what starting storage says.

## Integrity

- Tags froze each plan before its fit:
  [v0.1-prereg](https://github.com/gerardorosch02/alpine-hydro/tree/v0.1-prereg) (H1, H2),
  [v0.2-h3plan](https://github.com/gerardorosch02/alpine-hydro/tree/v0.2-h3plan) (H3a, H3b) and
  [v0.3-followup-plan](https://github.com/gerardorosch02/alpine-hydro/tree/v0.3-followup-plan)
  (post-hoc). v0.1 and v0.3 were pushed before their fits; v0.2 was tagged locally
  before any snow series existed but pushed after the H3 fit. v0.4 (water balance) was
  pushed before any 2026 number.
- Every open choice is dated in the deviations sections:
  [pre-registration](reports/results.md#deviations-from-the-pre-registration),
  [H3 plan](reports/results.md#deviations-from-the-h3-analysis-plan) and
  [MODIS fallback](reports/results.md#deviations-from-the-weekend-5-plan-modis-fallback).
- Every pre-registered test is reported, significant or not. Post-hoc work is labelled.

## Live this winter

- [Snow tracker](reports/figures/snow_tracker.png): daily snow cover against 2000 to 2025.
- [Live forecast](reports/figures/live_forecasts.png): one H1 forecast per SFOE week,
  November 2026 to April 2027, scored after April. A record, not a verdict.
- A keyless GitHub Action redraws the hero chart each SFOE week; a weekly laptop job
  updates snow and the live forecast ([log](reports/weekly_log.md)).

## Reproduce

```
git clone https://github.com/gerardorosch02/alpine-hydro.git
cd alpine-hydro
uv sync --locked
uv run alpinehydro demo    # rebuilds the figures from committed data, no keys needed
```

The full pipeline needs free accounts: ENTSO-E Transparency Platform, Google Earth
Engine, Copernicus Climate Data Store and NASA Earthdata (see `.env.example`).

## Data and licences

| Source | Used for | In this repo |
|---|---|---|
| SFOE weekly storage | Storage, validation, live weeks | Processed weekly tables |
| ENTSO-E Transparency Platform | Prices, controls, hydro generation | No price series; 11 yearly spreads; weekly hydro GWh |
| Copernicus Sentinel-2, USGS Landsat | Water masks | Derived tables only |
| swisstopo, SRTM, Copernicus GLO-30 | Outlines and terrain | Outlines and derived curves |
| ERA5-Land (Copernicus Climate Change Service) | Ice flag, snow water, temperature | Regional daily means |
| NASA MODIS and VIIRS snow cover | Snow tracker, Part C | Regional daily means |
| GLIMS | Glacier share (post-hoc) | Four numbers |
| SFOE production and pumping, HP-CatCH (ETH) | Water balance (post-hoc) | Weekly and monthly GWh, annual inflow |

Prices and generation: Source: ENTSO-E Transparency Platform. No raw ENTSO-E data is
included, only aggregated statistics, model results and charts, removed on request. Credit lines, links and dates checked:
[DATA_LICENCES.md](DATA_LICENCES.md). Code: MIT.

## Limitations

- **Ice in winter.** Lakes freeze from December to May, so the satellite is blind in
  the price season.
- **Terrain floors and mask edges.** swisstopo stores each lake as a flat surface 1 to
  10 m below full, so lower curves use 30 m global terrain; masks run 1.4% to 15% short.
- **Only about 11 winters of free prices** (CH from 2015).
- **Crisis winters dominate.** The H1 slope is −14.33 per 10 points in 2021/22 and
  2022/23 and −4.40 outside them.
- **Net refill includes operators' decisions.** End-of-September fill is inflow minus
  what operators chose to generate, not hydrology alone.
- **ENTSO-E covers only about 79% of Swiss storage hydro production**, so the water
  balance takes generation from SFOE.

## What I would do next

- Use the swisstopo lidar ground points to repair the lake curves where they are
  weakest.
- Get forward-price data, to test whether the storage signal is already priced in.

## Author

Gerardo Rosales: [GitHub](https://github.com/gerardorosch02),
[LinkedIn](https://www.linkedin.com/in/gerardorosales02/).
