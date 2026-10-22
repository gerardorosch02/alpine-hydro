# Water balance plan (post-hoc): was 2026 a weather story or an operator story?

Status: written on 2026-10-22 and frozen as the annotated git tag
`v0.4-waterbalance-plan`, pushed before any 2026 or 2022 balance, anomaly or comparison
was computed.

**This whole plan is post-hoc.** It was written after seeing the 2026 miss: the H3a
forecast made on 1 May said 82.6% full at the end of September, the actual was 74.0%,
and a post-hoc 1 July update gave 79.5%. It is a diagnostic, not a test. Every result
from it is labelled post-hoc, reported in its own section of `reports/results.md`
("Water balance 2026 (post-hoc diagnostic)"), and never mixed with the pre-registered
verdicts of H1, H2, H3a and H3b or with the follow-up verdict. It does not change
`prereg/PREREGISTRATION.md`, `prereg/H3_ANALYSIS_PLAN.md` or
`prereg/H3_FOLLOWUP_PLAN.md`. Any later choice is listed, with its date and reason,
under "Deviations from the water balance plan" in `reports/results.md`.

## 0. What was seen before this plan was written

Data availability only, checked on 2026-10-22:

- ENTSO-E CH generation per type has Hydro Water Reservoir (B12) and Hydro Pumped
  Storage (B10) generation. It has **no pumped-storage consumption** for CH (checked in
  2017, 2020, 2023, 2025 and 2026). CH generation per type starts on 1 July 2015 (no
  data on 1 March or 1 May 2015).
- SFOE daily production (energy dashboard, `ogd104_stromproduktion_swissgrid.csv`)
  runs from 2015-01-01 and has one "Speicherkraft" category (storage plus
  pumped-storage generation) and no pumping.
- SFOE monthly electricity balance (`ogd35`) has storage-plant generation
  (`Erzeugung_Speicherwerk_GWh`) and pumping (`Verbrauch_Speicherpumpen_GWh`) from
  2000 to August 2026 (2026 provisional). September 2026 is not published yet. While
  checking the column, the raw monthly 2026 pumping values (March to August) were
  printed. They were not compared with any other year.
- The SFOE weekly electricity balance (`ogd51`) is one Wednesday per week and ends in
  June 2026, so it cannot be summed into weeks. Not used.

Because of the missing pumping series, the owner chose on 2026-10-22: pumping from
SFOE `ogd35`, a primary window that ends on the last Sunday of August, and the two
secondary results in section 7.

## 1. Question

Over the 2026 refill season, was the record-low storage caused mainly by less water
coming in (weather) or by more energy being taken out by operators (release)?

## 2. The identity

For each SFOE week t (Monday 00:00 to Sunday 24:00 Europe/Zurich, ending on the Sunday
whose 24:00 content SFOE reports):

    implied inflow I_t = dS_t + G_res,t + G_ps,t - eta * P_t
    release R_t        = G_res,t + G_ps,t - eta * P_t
    so dS_t            = I_t - R_t

- dS_t: SFOE TotalCH content in GWh at Sunday t minus at Sunday t-1, from
  `data/processed/sfoe_storage_weekly.csv` (the CSV table the backtests use; it runs to
  Sunday 27 September 2026).
- G_res,t: ENTSO-E CH actual generation, Hydro Water Reservoir (B12), in GWh.
- G_ps,t: ENTSO-E CH actual generation, Hydro Pumped Storage (B10), in GWh.
- P_t: pumping in GWh. SFOE `ogd35` monthly `Verbrauch_Speicherpumpen_GWh`, spread
  evenly over the calendar days of its month (P_day = P_month / days in month), then
  summed over the 7 days of week t.
- eta = 0.75, the share of pumping energy that comes back as stored energy.
  Robustness: 0.70 and 0.80.

Run-of-river does not change storage and is not in the identity.

ENTSO-E energy: values at native resolution (hourly or 15-minute) are averaged into
hourly mean MW on the UTC axis, converted to Europe/Zurich, and summed over the hours of
the week (MWh, then GWh). A week with at least 90% of its hours present is scaled up:
GWh = mean MW over the present hours times the hours in the week. A week below 90% is a
gap week.

Stated simplifications: spill, evaporation and capacity changes are ignored. ENTSO-E is
national only, so the balance is national only. Some pumped storage moves water between
reservoirs that SFOE may not count. Spreading monthly pumping evenly over days ignores
its timing within the month, so single weeks are smoothed; window totals are not
affected except at the window's edges.

## 3. Years, windows and baseline

- Series: 1 July 2015 to the latest data.
- A year enters the baseline only if its window has no ENTSO-E gap week. 2015 fails this
  (generation starts 1 July 2015), so the expected baseline is **2016 to 2025**. Any other
  dropped year is reported.
- **Primary window:** from the last Sunday on or before 31 March (the start reading) to the
  last Sunday of August (the end reading); flows are summed over every week ending after
  the start reading up to the end reading. For 2026: Sunday 29 March to Sunday 30 August.
- **Update window:** the same start to the last Sunday of September (2026: Sunday 27
  September). Run once SFOE publishes September 2026 in `ogd35`, reported as an update.
- **Baseline for year Y:** the mean over the baseline years other than Y (so 2022 is not in
  its own baseline; for 2026 this is all of 2016 to 2025).

## 4. The decomposition

For year Y and a window: cumulative dS, I and R, and their anomalies against the baseline
mean (A_S, A_I, A_R). Because dS = I - R in every year, A_S = A_I - A_R exactly.

If A_S < 0, the storage shortfall is -A_S, and:

- inflow share = -A_I / -A_S
- release share = A_R / -A_S

The two shares add to 1. Either can be above 1 or below 0 (for example more water came in
but even more was released).

**Decision rule (primary window only, fixed now):**

- "Weather story" if the inflow share is at least 2/3.
- "Operator story" if the release share is at least 2/3.
- "Mixed" otherwise.
- If A_S >= 0 there is no shortfall to split; the label is "no shortfall".

The label is set at eta = 0.75. The shares and label at eta = 0.70 and 0.80 are reported,
with a statement of whether the label changes.

**Comparison year:** the same decomposition for 2022 (the other dry, high-price summer),
against the baseline without 2022.

## 5. Link to the snow forecast

The H3a walk-forward forecast for 2026 (82.622% full on Sunday 27 September, region
Total = Wallis, Graubuenden and Tessin) is a three-region number; the balance is
national. It is converted by keeping its forecast change in fill points:

    forecast national fill = national fill at the start + (82.622 - Total fill at the start)

where the start is the SFOE week that H3a used as starting storage for the 1 May 2026
issue (taken from `data/processed/snow/features_h3.csv`). Over the weeks from that start
to Sunday 27 September 2026, in national GWh and fill points of the 27 September national
capacity:

- forecast: the converted forecast fill;
- actual water, normal operators: start content + sum of the 2026 implied inflow - sum of
  the baseline mean release, over the same weeks;
- actual: SFOE TotalCH on 27 September.

The share of the forecast miss due to water = (forecast - actual water, normal operators)
/ (forecast - actual); the share due to release = the rest. Descriptive, no rule. It needs
September 2026 pumping, so until SFOE publishes it, it uses secondary result (a) and is
labelled provisional; it is rerun in the update.

## 6. Descriptive only, no test

A scatter of the weekly release anomaly (2026 or any year: R_t minus the baseline mean for
the same ISO week number, week 53 mapped to 52) against the weekly mean CH day-ahead price
(ENTSO-E, mean of the hours of the same Monday to Sunday), for weeks ending in April to
September, all years with no gap week (2026 to 30 August), coloured by year. Labelled
"descriptive". No conclusion about causes is drawn from it.

## 7. Secondary results (reported, never the label)

**(a) Provisional 1 April to 27 September 2026.** The update window, with September 2026
pumping set to the 2016 to 2025 mean September pumping, and a sensitivity at that mean
plus and minus 1 baseline standard deviation. Shares at each eta, labelled provisional.

**(b) All-SFOE monthly balance.** `ogd35` has monthly storage-plant generation
(`Erzeugung_Speicherwerk_GWh`, which includes pumped-storage plants). Monthly:

    I_m = dS_m + Gsp_m - eta * P_m

with dS_m from SFOE TotalCH content linearly interpolated (by time) between Sunday
readings to 24:00 on the last day of each month. Window April to August, same baseline
years and anomalies, shares at each eta. 2026 and any provisional month are marked. It is
a cross-check of the label only.

## 8. Kill criterion (applied before any 2026 or 2022 number)

Reconcile weekly ENTSO-E (B12 + B10) generation with SFOE daily "Speicherkraft"
(`ogd104`), summed over the same SFOE weeks, from 1 July 2015 to the last complete week.
Report the correlation, the mean percentage difference ((ENTSO-E - SFOE) / SFOE), the share
of weeks within 10%, and the same by year. Also report, without a threshold, monthly
ENTSO-E (B12 + B10) against `ogd35` `Erzeugung_Speicherwerk_GWh`.

**Stop and ask the owner** before anything for 2026 is computed if either:

- more than half of the overlap weeks differ by more than 10%, or
- the ENTSO-E B12 or B10 series misses more than 2% of hours from 1 July 2015 to
  27 September 2026, or has a gap week in the 2022 or 2026 window.

Note: `ogd104` is built from Swissgrid data, the same origin as ENTSO-E, so it checks
consistency rather than giving an independent measurement. `ogd35` comes from the SFOE
electricity statistics.

## 9. Sanity checks on implied inflow (before 2026)

- The share of weeks with negative implied inflow, all weeks and April to September.
- The seasonal shape: mean implied inflow by calendar month (week assigned to the month of
  its Sunday), expected to peak in June and July.
- Annual totals for 2016 to 2025 (calendar-year windows: last Sunday of the previous year
  to the last Sunday of the year) and their range.
- External: if accessible, annual implied inflow against HP-CatCH (ETH, CC BY) simulated
  natural inflow summed nationally, for the years both cover from 2016 to 2022, with the
  correlation. If it cannot be accessed, that is said.

These and the reconciliation are written to `reports/results.md` and committed before any
2026 number is computed.

## 10. Reporting and data

- Section "Water balance 2026 (post-hoc diagnostic)" in `reports/results.md`, label first.
- Figures: `water_balance_2026.png`, `water_balance_years.png`, `release_vs_price.png`.
- Committed: derived weekly and monthly GWh aggregates and the charts, credited, under the
  ENTSO-E decision of 22 October 2026 (credit, no raw data, removal on request). No raw
  ENTSO-E data. Whether the weekly mean prices behind the descriptive scatter may be
  committed is asked of the owner before they are.
- Data credits: Source: ENTSO-E Transparency Platform. Source: Swiss Federal Office of
  Energy SFOE.
