# H3 analysis plan: snow, refill and the autumn premium

Status: written on 2026-10-21 and frozen as the annotated git tag `v0.2-h3plan`
before any H3 model was fitted and before any correlation between a snow feature
and a target was computed. At the time of writing, no snow series had been
computed at all. The only Earth Engine work for Part C so far is listing which
collections and bands exist.

This plan fills in the details of the secondary hypotheses H3a and H3b named in
`prereg/PREREGISTRATION.md` (section 6, frozen as `v0.1-prereg`). It does not
change that file. Any later change to this plan is listed, with its date and
reason, in a section "Deviations from the H3 analysis plan" in
`reports/results.md`.

Items marked "(detail)" are points the brief for this weekend left open. They
were settled while writing this plan, before any data were computed.

## 1. Questions

- H3a (hydrology, exploratory): does snow on 1 April and 1 May forecast how
  full the alpine reservoirs are at the end of the filling season, beyond what
  the starting storage already says?
- H3b (price, exploratory): does the 1 May forecast of the end-of-season fill
  deviation relate to the CH minus DE-LU spread from October to December?

## 2. Regions

- The three alpine SFOE regions, Wallis, Graubuenden and Tessin, and their
  total.
- Outlines: the canton outlines of Valais, Graubünden and Ticino from swisstopo
  swissBOUNDARIES3D (release 2026-01, LV95). This is a stated simplification:
  canton outlines ignore tunnels and water diverted between catchments, and
  SFOE regions are defined by where the reservoirs are, not by where their
  water comes from.
- Total (detail): for snow, the mean over all valid pixels in the union of the
  three cantons, so it is area-weighted. For storage, the sum of the three
  regions' content divided by the sum of their weekly maximum capacity. It is
  not SFOE TotalCH, which also contains the rest of Switzerland.

## 3. Elevation bands

- Primary band: all land at or above 1800 m in each region. Robustness: 2000 m.
- DEM: Copernicus GLO-30 (detail: the current Earth Engine release
  `COPERNICUS/DEM/GLO30_2024_1`; the older `COPERNICUS/DEM/GLO30` asset is
  marked deprecated).
- On the 500 m MODIS grid (detail), a pixel is in the band if the mean GLO-30
  elevation inside it is at or above the threshold. Band areas are reported
  both from the 30 m DEM and as the count of 500 m pixels. Inland water is left
  out through the MODIS inland water class (detail).

## 4. Snow cover (MODIS)

- Source: MODIS MOD10A1 (Terra) and MYD10A1 (Aqua), collection 6.1,
  band `NDSI_Snow_Cover`, 500 m, from 24 February 2000 (Aqua from 4 July 2002).
  A pixel is valid when `NDSI_Snow_Cover` holds a value from 0 to 100. Cloud,
  night, missing, no decision, saturation, inland water and ocean are invalid.
- Fractional snow cover: FSC = -0.01 + 1.45 × NDSI (Salomonson and Appel),
  with NDSI = `NDSI_Snow_Cover` / 100, clipped to 0 to 1.
- Terra and Aqua: each day, take the valid value with the lower view zenith,
  or Terra if the zenith is unknown. The Earth Engine version of collection 6.1
  carries no view zenith band, so the zenith is always unknown (detail): the
  rule therefore takes Terra where Terra is valid and Aqua only where Terra is
  invalid.
- Cloud gaps: a pixel that is invalid on day d takes the most recent valid
  combined value from days d-1 to d-8. If there is none, the pixel is missing.
- The daily regional value is the mean FSC over valid (including gap-filled)
  pixels in the band. The valid share is valid pixels over all band pixels.
  The day is missing if the valid share is below 70%.
- Only region statistics are computed (`reduceRegion`). No image is exported.

## 5. Snow water equivalent (ERA5-Land)

- Source: ERA5-Land `snow_depth_water_equivalent`, daily mean, from
  `ECMWF/ERA5_LAND/DAILY_AGGR`, converted from metres to millimetres.
- Same regions and bands. Detail: ERA5-Land cells are about 9 km, so the value
  is sampled on the same 500 m grid as MODIS and averaged over the band pixels,
  which weights each cell by the area of band land it covers. ERA5-Land cells
  have their own mean elevation, usually well below 1800 m, so this is the SWE
  of the cells that hold high ground, not SWE at 1800 m.
- Daily from 1 January 1990 (detail), so that the strict 10-year robustness
  anomaly in section 7 is defined from 2001.

## 6. Issue dates and cut-offs

- Forecasts are issued on 1 April and 1 May each year.
- MODIS features use days up to and including the issue date minus 3 days.
- ERA5-Land features use days up to and including the issue date minus 7 days,
  as for HDD in H1.
- Starting storage uses the latest SFOE week whose known_time (weekend 3 rule:
  the Thursday 23:59 Europe/Zurich after the valid Sunday) is at or before the
  issue date, 23:59 Europe/Zurich (detail).

## 7. Features at each issue date

- Snow predictor (primary, both sources): the raw mean of the daily regional
  value (FSC, or SWE in mm) over the 8 days ending at the cut-off. No anomaly is
  subtracted. With an intercept and walk-forward fitting, the slope on the raw
  value is the same as the slope on its anomaly against the training-years
  mean, which is past-only by construction. This choice was made on 2026-10-21
  because MODIS starts in 2000: a trailing 10-year anomaly would exist only from
  2010, and with at least 10 training years the first MODIS test year would
  move from 2011 to 2020. Both sources are built the same way so the MODIS and
  ERA5-Land versions are comparable.
- Missing days (detail): missing days are left out of the 8-day mean. If fewer
  than 4 of the 8 days are present, the feature is missing and that year is
  dropped from that model. Every dropped year is reported.
- Robustness only, ERA5-Land: a strict trailing 10-year anomaly, the 8-day mean
  minus the mean of the same 8 calendar days in each of the previous 10 years
  (29 February is left out of the calendar-day match).
- Starting storage: the SFOE fill of that region (section 6), in percentage
  points of that week's capacity.

## 8. Targets

- H3a, primary: SFOE fill on the last Sunday of September of the same year
  (the SFOE `valid_time` falling on that Sunday), in percentage points of that
  week's capacity, for each region and the total. 2026 is included (valid
  Sunday 27 September 2026 is in the CSV).
- H3a, secondary: refill in GWh, the content on the last Sunday of September
  minus the lowest weekly content with a valid Sunday from 1 February to
  31 May of the same year. The refill models use the same predictors as the
  fill models.
- H3b: the mean daily CH minus DE-LU day-ahead baseload spread over the
  delivery days 1 October to 31 December of the same year, 2015 to 2025. Daily
  baseload is built exactly as in H1 (Europe/Zurich delivery days, hourly means
  first, DE-AT-LU before 2018-10-01). Only one yearly number is committed; the
  price series is never committed.

## 9. H3a models

- Full model: fill at end of September = a + b × snow + c × starting storage,
  fitted by OLS. One version with MODIS FSC, one with ERA5-Land SWE.
- C0, climatology: the mean end-of-season fill over the previous 10 years.
- C1, starting storage only: fill = a + c × starting storage. C1 is nested in
  the full model.
- Sample years (detail): 2001 to 2026 for every H3a model, both sources.

## 10. H3a scoring

- Primary scoring: walk-forward on an expanding window. The model for test
  year Y is fitted on every sample year from 2001 to Y-1, so the first test year
  2011 has exactly 10 training years. Test years are 2011 to 2026 (16 years).
- Secondary scoring: leave-one-year-out across 2001 to 2026. Each year is
  predicted by models fitted on the other 25 years; in this scheme C0 is the
  mean of the other 25 years (detail). This is not a forecast claim.
- Skill score against C0 and C1: 1 - MSE(full) / MSE(benchmark).
- Clark-West test of the full model against C1, one-sided (the full model is
  better). Detail: one forecast per year, so no overlap; the statistic is the
  mean of the Clark-West adjusted loss differences divided by its standard
  error, with a one-sided p from a t distribution with n - 1 degrees of freedom.
- Diebold-Mariano of the full model against C0 with the Harvey-Leybourne-Newbold
  small-sample correction, horizon h = 1, squared-error loss, two-sided p from
  a t distribution with n - 1 degrees of freedom (detail, as in H1 deviation D5).
- What counts: the primary result is the total region, MODIS version, 1 May
  issue, 1800 m band, end-of-September fill, walk-forward. Regions, ERA5-Land,
  1 April, the 2000 m band, the refill target, leave-one-year-out and the ERA5-Land
  strict-anomaly version are secondary and reported without multiple-testing
  correction.

## 11. H3a pass mark

The primary version passes only if its walk-forward skill score against C1 is
above 0 and its Holm-adjusted Clark-West p (section 13) is below 0.05. Anything
else is reported as "no added skill from snow".

## 12. H3b model

- Predictor x for year Y: the walk-forward H3a primary forecast (total, MODIS,
  1 May, 1800 m) of the end-of-September fill, minus the 10-year norm for that
  week (detail: the past-only median of the same ISO week over Y-10 to Y-1,
  as `norms.py` computes it for H1, applied to the three-region total), in
  percentage points.
- Target y: the October to December spread (section 8), years 2015 to 2025
  (11 years).
- Regression: y = a + b × x by OLS on the 11 years. Report the slope per
  10 points and its 95% interval from HC3 standard errors (t distribution,
  n - 2 degrees of freedom).
- Clark-West against an intercept-only model, one-sided. Detail: out-of-sample
  forecasts from an expanding window with at least 5 training years, so the
  test years are 2020 to 2025 (6 years); p from a t distribution with n - 1
  degrees of freedom.
- Smallest detectable effect (detail): (t(0.975, n - 2) + t(0.80, n - 2)) × the
  HC3 standard error of the slope, per 10 points. That is the slope the design
  would detect with 80% power at 5% two-sided.

## 13. Multiple testing

- Holm correction across the secondary family H2, H3a (primary version) and
  H3b, at 5%. The p-values entered are: H2, the Clark-West p already reported
  in weekend 3; H3a, the primary walk-forward Clark-West p against C1; H3b, the
  Clark-West p against the intercept-only model.
- N1 is not run, because Part A was closed and its timing ceiling was about
  EUR 0.2/MWh. This is recorded as a dated deviation from the pre-registration
  in `reports/results.md`.

## 14. Look-ahead safeguards

Tests check that every feature's latest input day is at or before its cut-off,
that starting storage was known at the issue date, and that every trailing
10-year baseline (C0, the ERA5-Land robustness anomaly and the H3b norm) uses
earlier years only.

## 15. Data credits

- MODIS snow cover: Hall, D. K. and G. A. Riggs (2021). MODIS/Terra and
  MODIS/Aqua Snow Cover Daily L3 Global 500m SIN Grid, Version 61. NASA National
  Snow and Ice Data Center DAAC.
- ERA5-Land: Muñoz Sabater, J. (2019), Copernicus Climate Change Service (C3S)
  Climate Data Store.
- Outlines: swissBOUNDARIES3D, © swisstopo.
- DEM: Copernicus GLO-30, © DLR e.V. 2010-2014 and © Airbus Defence and Space
  GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.
