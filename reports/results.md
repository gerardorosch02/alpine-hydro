# Results

Weekend 1 (2026-10-20). No price slope, regression or price chart has been
computed. Machine-readable versions of the checks are in `reports/checks/`.

## Step 0 findings

**SFOE CSV is updating, but lags the PDF.** On 2026-10-20 the ogd17 CSV ended
at Datum 2026-09-28 (valid Sunday 2026-09-27), HTTP Last-Modified
Tue 29 Sep 2026 13:55 UTC. The 2026 weekly PDF (`12445-Montagswerte_12.10.2026.pdf`,
Last-Modified Tue 13 Oct 2026 09:48 UTC) already had 05.10 and 12.10.2026,
so the CSV was two weeks behind. Decision: CSV only for now, the release log
also watches the PDF, and a PDF parser is planned for weekend 6. Both files
have so far appeared on a Tuesday, earlier than the conservative Thursday
23:59 known_time used for history.

**Maximum capacity changes often.** TotalCH maximum moves between 8,500 GWh
(2000) and 8,900 GWh, with small steps up and down (8,820 in 2015/16,
8,895 since March 2023, 8,900 for September to December 2024). Fill is
always content over the same week's maximum.

**CH day-ahead prices on ENTSO-E** are continuous from 2015-01-01 00:00
Europe/Zurich. Before that only isolated days exist (2014-01-08, 2014-12-02,
2014-12-23). DE-LU, FR and IT-North are continuous from 2015-01-05. After
2015, no zone has a missing or partial delivery day up to 2026-10-21.
Note: entsoe-py returns empty hours as NaN rows, which made a first probe
look continuous from 2014-12-02; the counts above exclude NaN.

**ENTSO-E does carry a Swiss reservoir series** (`query_aggregate_water_reservoirs_and_hydro_storage`,
weekly, MWh), from 2015-02-23 to 2026-09-28, 603 weeks. It is not an
independent source. From the week of 2024-12-30 it equals SFOE TotalCH
exactly (mean absolute difference 0.0 GWh in 2025 and 2026). Before that it
is a different, smaller aggregate: 52% to 78% of the SFOE total by year
(median ratio), correlation with SFOE 0.965 to 0.998, mean absolute
difference 1,100 to 2,100 GWh. SFOE remains the primary series.

**ENTSO-E terms.** Terms of Use of 29 March 2023 and the "List of data
available for free re-use" of 18 October 2023:
https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions
Listed items are CC-BY 4.0. Day-ahead prices (article 12.1.d) and reservoir
filling (16.1.d) are not on the list, and clause 3.1 asks users to seek the
primary owner's agreement where re-use could harm their rights. So no
ENTSO-E price data of any kind are committed, including derived statistics
of price levels. Only statistics of my own data checks are committed.

**SMARD is a clean cross-check.** Market data are CC BY 4.0, credit
"Bundesnetzagentur | SMARD.de" (https://www.smard.de/home/datennutzung).
Hourly prices, 2018-10-01 to 2026-10-21, against ENTSO-E hourly means:

| Zone | Hours | Correlation | Mean abs. difference (EUR/MWh) | Max abs. difference |
|---|---|---|---|---|
| CH | 70,632 | 1.000000 | 0.0000 | 0.000 |
| DE-LU | 70,608 | 1.000000 | 0.0003 | 0.005 |
| FR | 70,632 | 1.000000 | 0.0003 | 0.005 |

Every hour matches to within EUR 0.01, including after the October 2025
switch to 15-minute products, so SMARD's hourly series equals the hourly
mean of the 15-minute ENTSO-E prices. Hour sets are identical.

## Current storage

Week ending Sunday 27 Sep 2026 (latest CSV week): TotalCH 6,588 GWh of
8,895 GWh, **74.1% full**. The 10-year past-only norm for that week is
85.2%, so the deviation is **-11.2 points**. The 20-year norm is 85.5%
(-11.5 points). The PDF shows 73.6% on 12.10.2026, not yet in the CSV.

2025/26 was below the 2000/01 to 2024/25 minimum for the same week in 17
weeks: 17 and 24 May, 21 and 28 June, and every week from 5 July to
27 September 2026. On 27 September it was 77.6% at the previous minimum,
3.5 points lower. This is a description of storage only, not a price claim.

![Hero chart](figures/hero_storage.png)

## Timing ceiling (SFOE only, no prices)

Standard deviation of the week-on-week change in the deviation, November
to April, scaled to a 4-day head start and multiplied by the smallest
effect of interest (EUR 2/MWh per 10 points):

| Norm | Weekly changes | SD of weekly change (pp) | 4-day SD, linear (pp) | 4-day SD, square root (pp) | Ceiling, linear (EUR/MWh) | Ceiling, square root (EUR/MWh) |
|---|---|---|---|---|---|---|
| 10-year | 431 (2010-01 to 2026-04) | 1.50 | 0.86 | 1.14 | **0.17** | **0.23** |
| 20-year | 172 (2020-01 to 2026-04) | 1.44 | 0.82 | 1.09 | 0.16 | 0.22 |

Both ceilings are below EUR 0.5/MWh. The timing edge from a few days'
satellite head start is likely worthless. Part A should be framed as
per-reservoir detail (which reservoirs, which valleys, how they fill),
not as a faster version of the SFOE number.

## Part A: satellite storage (weekend 2, closed)

Part A was an experiment in where free satellite data (Sentinel-2 from 2017,
Landsat 8 and 9 from 2013) can and can't track Alpine storage. Water masks
come from MNDWI with a per-scene Otsu threshold. A level is read by matching
each mask to terrain from swissALTI3D, a global DEM and a fitted curve, and
volume and energy follow from the reservoir's curve and energy coefficient.
Machine-readable results: `reports/checks/wallis_validation.json`,
`data/processed/satellite/`.

### Wallis validation: pass

Satellite Wallis is the energy sum of Lac des Dix, Lac d'Emosson and Lac de
Mauvoisin, calibrated to SFOE Wallis with only a scale and an offset, walk-forward
by hydrological year. The first year (2013/14, 2 ok weeks) is in-sample and left
out. Scored on anomalies (deviation from the same week's mean across the other
years) for June to November weeks where all three lakes have an ok scene within
3 days of the SFOE week end.

| | R² of anomalies | MAE (pp of capacity) | Fill bias (pp) | Fill MAE (pp) | n weeks | Result |
|---|---|---|---|---|---|---|
| **Dix + Emosson + Mauvoisin** | **0.695** | 2.67 | +0.31 | 2.04 | 46 | **pass** (mark 0.50) |
| Sensitivity: without Mauvoisin | 0.715 | 3.33 | +0.98 | 2.56 | 56 | pass |

The sensitivity drops Mauvoisin, whose fill is indicative. It is a check, not
the main result. Scored years run from 2017/18 to 2025/26. The anomaly bias is
zero by construction (leave-one-year-out anomalies sum to zero each week), so
the table gives the bias and error of the calibrated fill itself.

By month (main result). No June or November week had all three lakes ok.

| Month | n | R² | MAE (pp) | SD of SFOE anomaly (pp) |
|---|---|---|---|---|
| July | 9 | 0.66 | 4.64 | 9.1 |
| August | 11 | 0.89 | 2.27 | 7.8 |
| September | 12 | 0.01 | 2.46 | 3.0 |
| October | 14 | 0.44 | 1.91 | 3.0 |

![Validation scatter](figures/validation_scatter.png)

**What worked and what failed.** The pass rests on July and August, when the
lakes are filling and years differ by up to 17 points. In late July 2026, for
example, SFOE Wallis was 14 to 17 points below the same weeks of other years and
the satellite showed 15 points below; in early August 2024 SFOE was 13 points
above and the satellite 8 above. In September and October the lakes sit near
full and SFOE anomalies are small (SD 3 pp). The satellite cannot see them,
because near the top the masks run a few percent short of the true area along
the shore, and that shortfall hides the last metres of level. At Emosson,
ok levels never pass the swissALTI3D floor (1920.4 m) although full supply is
1930 m. June and November fail for a different reason: snow, lake ice and
cloud, so no week has all three lakes clear. Only 54 of the weeks since 2013
had all three lakes ok, and the sample is small: 46 scored weeks over 13
calendar weeks. The first out-of-sample year (2017/18) is calibrated on just
2 Landsat weeks.

**Robustness checks (added 2026-10-21, weekend 3).** These do not change the
pass recorded under the stated rule. Each drops some weeks from the scored set
and recomputes the anomalies on the weeks that remain; the walk-forward
calibration is unchanged (`reports/checks/wallis_robustness.json`).

| Check | R² of anomalies | MAE (pp) | n weeks |
|---|---|---|---|
| Stated result, all scored weeks | 0.695 | 2.67 | 46 |
| Without calendar year 2026 (the most extreme year) | 0.408 | 2.75 | 40 |
| Without calendar year 2022 | 0.743 | 2.59 | 39 |
| Without the first scored year 2017/18 (calibrated on 2 Landsat weeks) | 0.744 | 2.80 | 41 |

Without 2026 the R² falls below the 0.50 mark. The 2026 drought summer, with
SFOE Wallis 14 to 17 points below other years in late July, carries a large
part of the result. Dropping 2022 or the weakly calibrated first year does not
weaken it.

**Stated uncertainty: mask edge bias.** Against lidar water levels on the
flight day, the masks were 1.4% to 15% short of the true lake area
(clean tests at Sihlsee, Gruyère and Emosson; `reports/checks/mask_edge_bias.json`).
The shortfall is not consistent between lakes, so it is not corrected. It is
roughly one 10 m pixel along the whole shore, more on steep wooded banks.

### Coverage

Share of SFOE weeks (from April 2017, in searched months) whose closest scene
within 3 days falls in each class:

| Reservoir | ok | Level not trusted | Ice or snow | Cloud | No scene |
|---|---|---|---|---|---|
| Sihlsee (all months) | 28% | 22% | 15% | 33% | 1% |
| Lac de la Gruyère (all months) | 3% | 46% | 5% | 45% | 1% |
| Lac des Dix (June to November) | 40% | 8% | 8% | 41% | 4% |
| Lac d'Emosson (June to November) | 33% | 10% | 7% | 50% | 1% |
| Lac de Mauvoisin (June to November) | 37% | 4% | 17% | 39% | 4% |

Share of weeks with an ok scene, by month:

| Month | Dix | Emosson | Mauvoisin |
|---|---|---|---|
| June | 33% | 12% | 14% |
| July | 55% | 36% | 34% |
| August | 39% | 55% | 45% |
| September | 42% | 47% | 51% |
| October | 48% | 42% | 52% |
| November | 21% | 3% | 21% |

![Coverage map](figures/coverage_map.png)

### Fill quality per reservoir

- **Lac de la Gruyère: fill not usable.** Its scenes table is kept for the
  coverage figure, but its levels and fill are not used. Two problems meet at
  the same heights. Below the swissALTI3D floor (674.02 m), the GLO-30 band is
  nearly flat: the lake area grows by only 0.02 km² per metre from 669 to
  674 m, against 0.38 km² per metre in the 3 m above the floor. And the summer
  water masks cover about 7.9 km², 3 to 5% short of the 8.30 km² lake at the
  floor. On this curve that shortfall alone moves the level by about 6 m. The
  result is a level series flat at 667 to 670 m all year.
- **Lac de Mauvoisin: indicative.** Its fitted curve hit the lower bound b = 1,
  27% of its usable volume is fitted, and its curve failed the continuity check
  (ratio 0.23 against a mark of 0.25).
- **Grimsel: indicative** (continuity ratio 0.248). Not run this weekend.
- Lei and Grimsel batches and the DAHITI altimetry check are out of scope:
  Part A closed after the Wallis validation.
- Sihlsee is shown beside the SFOE "rest of Switzerland" region as a visual
  check only. One lake cannot stand in for a region.

![Sihlsee](figures/sihlsee_showcase.png)

## Deviations from the pre-registration

The frozen text is `prereg/PREREGISTRATION.md` at tag `v0.1-prereg`; it is not edited.
Every entry below clarifies a point the text leaves open, or records a data access
choice. All were fixed on **2026-10-21, before any price model was fitted** (this section
was committed before the first fit). None changes a rule after seeing a result.

| # | Date | Point | Choice | Reason |
|---|---|---|---|---|
| D1 | 2026-10-21 | Month used for the dummies, B0 and B2 | The valid Sunday's month | Origins from late-April Sundays fall on a Thursday in May; the valid Sunday keeps the six season months that define the sample. |
| D2 | 2026-10-21 | Winsorising test rows | Test x and test y are clipped at the training cut-offs, and the primary scores use that clipped y. A robustness score uses the raw test y. | The text winsorises "y and x" with training cut-offs; applied literally. Cut-offs from pre-crisis training years clip the 2021/22 and 2022/23 test winters, so both scores are reported. |
| D3 | 2026-10-21 | The "in-sample slope" | Full model on all origins 2015/16 to 2025/26, full-sample cut-offs, Newey-West lag 4 (8 as robustness). Rule 2 uses the 95% interval as written; TOST p-values are reported beside it. | The text says "95% interval … (TOST at 5%)", but TOST at 5% corresponds to a 90% interval. The rule's wording (95%) is applied; the inconsistency is noted, not resolved in either direction after results. |
| D4 | 2026-10-21 | Crisis-excluded variant | 2021/22 and 2022/23 are dropped from training and test; test winters 2023/24 to 2025/26 | A variant "without the crisis winters" should not learn from them either. |
| D5 | 2026-10-21 | Clark-West and Diebold-Mariano on overlapping weekly targets | Errors pooled over the 5 test winters. Clark-West: Newey-West lag 4 variance, one-sided normal p. Diebold-Mariano: variance with lags 1 to 3, Harvey-Leybourne-Newbold correction with h = 4, two-sided t p with n − 1 df. | Consistent with the lag-4 primary test; h = 4 weeks of overlap for a 28-day target from weekly origins. |
| D6 | 2026-10-21 | B1 window | The 28 delivery days ending the day before the origin day | Conservative reading of "the 28 days before the origin". |
| D7 | 2026-10-21 | Bootstrap | 2,000 resamples of whole winters, seed 20261021. Slope: the 11 winters resampled and re-winsorised each time. Out-of-sample R² against B3: the 5 test winters resampled. | Five test winters give only 126 distinct resamples, so that interval is coarse. |
| D8 | 2026-10-21 | H2 specification | Origins with a valid Sunday in March or April; target the 28-day CH minus IT-North spread; the H1 controls; the same folds; test = one-sided Clark-West of the full model against B3. Holm family "H2 only so far", recomputed when H3b and N1 are added. | The text names H2 but no test. |
| D9 | 2026-10-21 | Gaps in the controls | Each generation control is the mean MW over all available hours in its window; partial days count with the hours they have. Pre-stated floor: a window with less than 90% of its expected hours (or days, for HDD) sets that control to missing and drops the origin from that model. Dropped: 0 origins in every model (lowest coverage 96.3%, French nuclear). | French nuclear has 27 days with 1 to 3 missing hours and 2026-01-01 with 1 of 24 hours (confirmed at the source), some inside test-winter windows. "Mean MW over the window" read literally. |
| D10 | 2026-10-21 | HDD source | ERA5-Land daily aggregates through Earth Engine (`ECMWF/ERA5_LAND/DAILY_AGGR`), country outlines `USDOS/LSIB_SIMPLE/2017`, area-weighted with pixel areas over land cells | Same dataset as the Copernicus portal named in the text; a different access route. |
| D11 | 2026-10-21 | Crisis-interaction variant | Full-sample in-sample OLS with x, a crisis-winter dummy and x × crisis (2021/22, 2022/23) | The text asks for "a crisis-winter interaction on the slope"; the level dummy keeps the interaction from absorbing a level shift. Reported only; not part of the rule. |
| D12 | 2026-10-21 | Verdict labels | If rule line 2 holds: "no effect (equivalence)". Else if line 1 or 3 holds: "no edge". Else: "edge". | The rule defines "no edge"; line 2 is the equivalence case, the stronger statement. |
| D13 | 2026-10-21 | Benchmark inputs | B1 and B2 use the raw 28-day spread before the origin (not winsorised); B0 and B2 average the clipped training y; controls are not winsorised | The text winsorises only x and y. |
