# H3 follow-up plan (post-hoc): summer updates and a higher snow band

Status: written on 2026-10-22 and frozen as the annotated git tag `v0.3-followup-plan`
before any follow-up feature was computed and before any follow-up model was fitted.

**This whole plan is post-hoc.** It was written after seeing the H3a result (no added
skill from snow on 1 May: skill against C1 +0.175, Clark-West p 0.134, Holm 0.268) and
the 2026 miss (1 May forecast 82.6% against an actual 74.0%). Every result from it is
labelled post-hoc, reported in its own section of `reports/results.md`, and never mixed
with the pre-registered verdicts of H1, H2, H3a and H3b. It does not change
`prereg/PREREGISTRATION.md` (`v0.1-prereg`) or `prereg/H3_ANALYSIS_PLAN.md`
(`v0.2-h3plan`). Any later change is listed, with its date and reason, under
"Deviations from the follow-up plan" in `reports/results.md`.

## 1. Questions

- Does what happens after 1 May (glacier melt from high ground, and rain) improve the
  forecast of the end-of-September fill, beyond the storage known at the time?
- Does snow cover at or above 2500 m on 1 April carry information that the 1800 m band,
  which is still saturated then, does not?

## 2. Everything kept from the H3 analysis plan

Regions (canton outlines of Wallis, Graubuenden, Tessin; Total as in the H3 plan),
target (SFOE fill on the last Sunday of September, percentage points of that week's
capacity), the MODIS snow series and its rules, the starting-storage rule (latest SFOE
week whose Thursday 23:59 known_time is at or before the issue date, 23:59
Europe/Zurich), the 8-day snow window, the MODIS cut-off (issue minus 3 days) and the
ERA5-Land cut-off (issue minus 7 days), OLS, Clark-West and skill exactly as in
`evaluate_snow.py`.

## 3. Primary version (one)

- Issue date: **1 July**. Region: **Total**. Scoring: **walk-forward**, expanding window,
  sample years 2001 to 2026, **test years 2012 to 2026** (15 years; the first test year
  has the 2001 to 2011 training years less any year with a missing feature).
- Full model:
  fill = a + b × FSC(1 May, 1800 m) + c × storage(1 July) + d × PDDG(1 July) + e × P(1 July)
- Benchmark **C1**: fill = a + c × storage(1 July), the storage known at the same issue
  date. C1 is nested in the full model.
- Test: one-sided Clark-West of the full model against C1, as in H3a (one forecast per
  year, p from a t distribution with n − 1 degrees of freedom). Skill against C1:
  1 − MSE(full) / MSE(C1).

## 4. Features

- FSC(1 May, 1800 m): the H3a primary snow feature, unchanged (8-day mean ending
  28 April).
- storage(D): the H3 starting-storage rule applied at issue date D.
- PDD(D): positive degree-days above 2500 m. Daily ERA5-Land mean 2 m temperature
  (`ECMWF/ERA5_LAND/DAILY_AGGR`, `temperature_2m`), averaged over the 500 m pixels at or
  above 2500 m in the region (same sampling as the H3 SWE series); PDD = sum over the
  days from 1 May to the ERA5-Land cut-off (D minus 7 days) of max(0, T in C).
- Glacier share G: glacier area inside the region divided by the region's land area at or
  above 2500 m, from the GLIMS glacier database in Earth Engine (`GLIMS/20230607`),
  outlines with a source date from 2013 to 2016 (the Swiss Glacier Inventory 2016 epoch,
  submitted by the University of Zurich), unioned so overlaps count once. One static
  value per region. PDDG = PDD × G. For a single region G is a constant, so PDDG is a
  rescaled PDD; the product is kept so the regions are comparable.
- P(D): precipitation to date. ERA5-Land `total_precipitation_sum`, mean over the 1800 m
  band pixels of the region, summed from 1 May to the ERA5-Land cut-off, in mm.
- The 2500 m band: every 500 m MODIS pixel whose mean GLO-30 elevation is at or above
  2500 m, inland water removed, built once as polygons per canton like the 1800 m band.
- Missing features: a year with any missing feature is dropped from that model and
  reported; the H3 rule for the 8-day snow window (at least 4 of 8 days) applies.

## 5. Secondary versions (reported, Holm-corrected, not the verdict)

1. 1 June update: as the primary, with D = 1 June.
2. 1 August update: as the primary, with D = 1 August.
3. 2500 m on 1 April: the H3a 1 April model with FSC at or above 2500 m (8-day mean
   ending 29 March) in place of the 1800 m FSC; benchmark C1 with 1 April storage.

All three are Total, walk-forward, test years 2012 to 2026. Region-level results for
the primary specification are reported without correction.

## 6. Multiple testing and pass mark

- Holm correction within this follow-up family only: the primary and the three
  secondary Clark-West p-values (four tests). The pre-registered Holm family (H2, H3a,
  H3b) is not touched.
- The primary passes only if its walk-forward skill against C1 is above 0 and its
  Holm-adjusted Clark-West p is below 0.05. Anything else is "no added skill after
  1 May (post-hoc)".

## 7. Reporting

- A separate section "Follow-up (post-hoc)" in `reports/results.md`.
- The 2026 case for every issue date (1 April 2500 m, 1 June, 1 July, 1 August): the
  forecast of the full model and of C1 against the actual end-of-September fill.
- Earth Engine work is tagged `alpinehydro-weekend5`; one chunk is tested before any
  full run; the owner is asked first if the estimate is above 5 EECU-hours.

## 8. Look-ahead safeguards

Tests check that every ERA5-Land day used is at or before D minus 7 days, every MODIS
day at or before the issue minus 3 days, and that storage(D) was known at D.

## 9. Data credits

As in the H3 plan, plus: GLIMS Consortium (2005, updated 2023). GLIMS Glacier Database,
Version 1. NSIDC; Swiss outlines from the Swiss Glacier Inventory (University of Zurich,
GLAMOS).
