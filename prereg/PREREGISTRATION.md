# Pre-registration: Swiss storage deviation and the CH minus DE-LU spread

Status: FROZEN on 2026-10-20 as git tag `v0.1-prereg`, before any price
model was run. Any later change is listed under "Deviations from the
pre-registration" (section 10). No price slope, price regression or price
chart has been looked at while writing it. The only price work so far is
downloading, resampling and checking that two price sources agree with each
other. Coverage of the control series was checked by counting values per
day, without looking at their levels.

## 1. Primary hypothesis H1

From November to April, the SFOE national fill deviation from its trailing
10-year same-week median, as known on its release day, predicts the mean
CH minus DE-LU day-ahead baseload spread over the next 4 weeks. Expected sign:
negative (lower Swiss storage than normal goes with a higher Swiss premium).

### Variables

- Predictor x: `dev_10y_pp`, SFOE TotalCH fill minus the median fill of the same
  ISO week in the previous 10 years, in percentage points. Fill is content
  divided by that week's maximum capacity. Week 53 uses the week-52 norm. The
  norm uses past years only (tested in `tests/test_norms.py`).
- Release day and known_time:
  - Historical rows use a conservative known_time of Thursday 23:59
    Europe/Zurich after the Sunday the reading describes. The weekly PDF has
    been observed online on the Tuesday (the 12.10.2026 PDF had Last-Modified
    Tue 13 Oct 2026 09:48 UTC), so Thursday is later than the real release.
  - Live known_time comes from the release log (`data/processed/sfoe_release_log.csv`
    and `data/processed/sfoe_pdf_log.csv`), which records when each new CSV
    week and each new PDF version is first seen. The CSV has lagged the PDF by
    about two weeks in October 2026, so the PDF log is the live source.
- Forecast origin: known_time. The origin day is the Europe/Zurich date of
  known_time (a Thursday for historical rows).
- Target y: the mean of the daily CH minus DE-LU baseload spread (EUR/MWh) over
  the 28 delivery days that start with the delivery day of the first Swiss
  day-ahead auction held after known_time. The Swiss auction closes at 11:00
  Europe/Zurich for the next day, so a Thursday 23:59 known_time gives a
  Friday auction and a window that starts on Saturday. Daily baseload is the
  mean of the hours of the Europe/Zurich delivery day (23, 24 or 25 hours).
  DE-LU uses DE-AT-LU before 2018-10-01. Since 2025-10-01 coupled zones clear
  in 15-minute steps; all prices are averaged to hours first.
- Season: forecast origins whose valid Sunday falls in November to April.
- Outliers: y and x are winsorised at the 1st and 99th percentile, with the
  cut-offs estimated on the training window of each fold only.

### Controls

All primary controls are realised values over the 28 days before the
forecast origin, using only days published before known_time. No forecasts
are used, because no free archive of past forecasts exists. B3 and the full
model always use identical controls, in every variant.

| Control | Definition | Window | Source and coverage (checked 2026-10-20) |
|---|---|---|---|
| French nuclear | Mean MW of actual generation, nuclear (B14) | The 28 Europe/Zurich days ending the day before the origin day | ENTSO-E actual generation per type, FR. Every day from 2015-01-01 to 2026-10-19 present. Hourly until mid-December 2024, then 15-minute. |
| Swiss nuclear | Mean MW of actual generation, nuclear (B14) | The 28 days ending 7 days before the origin day (as for HDD), because CH publication timing is not guaranteed | ENTSO-E, CH. Continuous from 2015-07-01; before that only 2015-04-21 to 2015-04-23. Every day from 2015-07-01 to 2026-10-19 present. The first control window needed starts in October 2015, so Swissgrid data are not needed. |
| German wind | Mean MW of actual generation, wind onshore (B19) plus wind offshore (B18) | As above | ENTSO-E, area DE (country level, so it spans the 2018 DE-AT split). Both series have every day from 2015-01-01 to 2026-10-19. Year-long requests for onshore fail for 2015, 2016 and 2025 (entsoe-py parsing error, one HTTP 599) and return one month for 2021; month-by-month requests return every day. The fetcher must request onshore wind by month. |
| CH and DE heating degree days | Mean daily HDD, base 15.5 C: HDD = max(0, 15.5 - T), where T is the daily mean 2 m temperature from ERA5-Land, averaged over the land grid cells of the country (area-weighted) | The 28 days ending 7 days before the origin day | ERA5-Land daily statistics (Copernicus CDS), January 1950 onwards, published with a delay of about 6 days. The 7-day lag keeps every day used before known_time. |
| Climatological HDD for the target window | For each day of the 28-day target window, the mean HDD of the same calendar day (29 February uses 28 February) over the 10 most recent years in which that calendar day falls before the origin day; then the mean over the 28 days. Computed for CH and DE. | The target window, from past years only | ERA5-Land as above. Ten past years are available from 2005 onwards, so this is defined for every origin. |
| Month dummies | One dummy per origin month, November as the base | n/a | n/a |

The ENTSO-E series must be published before known_time. Regulation (EU)
543/2013, Article 16(2)(b), requires aggregated generation per production
type (Article 16(1)(b)) no later than one hour after the operational period,
so for FR and DE the day before the origin day is complete well before a
Thursday 23:59 known_time. Switzerland is not bound by the regulation and
Swissgrid reports voluntarily, so the CH publication delay is not
guaranteed; the Swiss nuclear window therefore ends 7 days before the
origin day, the same lag as HDD.

Generation controls are mean MW over the window. Where the source is in
15-minute steps (FR from December 2024, DE throughout), the values are
averaged, never summed, so every control is in MW whatever the resolution.

### Sample

CH day-ahead prices on ENTSO-E are continuous from 2015-01-01 (DE-LU, FR and
IT-North from 2015-01-05; CH has only isolated days in 2014). The first full
winter is therefore 2015/16. The first year with 10 prior years of SFOE data
is 2010, so the 10-year norm is defined for every origin. With at least
6 training winters the first test winter is 2021/22, which gives 5 test
winters: 2021/22, 2022/23, 2023/24, 2024/25 and 2025/26.

## 2. Benchmarks

- B0: seasonal norm. The spread forecast is the training-mean spread for that
  calendar month (no storage information).
- B1: last value carried forward. The forecast is the spread over the 28
  days before the origin.
- B2: persistence plus the usual seasonal change: B1 plus the training-mean
  change between that 28-day window and the next for the same calendar month.
- B3: controls only (the H1 model without the storage deviation).
- Full model: B3 plus `dev_10y_pp`.

## 3. Walk-forward design

- Folds are hydrological years (1 October to 30 September). Each fold is
  estimated on all earlier data (expanding window), re-estimated each
  1 October.
- A 4-week gap separates the end of the training targets and the first test
  origin, so no training target overlaps a test target.
- At least 6 training winters are required before a winter is used as a test.

## 4. Tests

- Newey-West (HAC) standard errors for the in-sample slope with a lag of
  exactly 4 for the primary test, because the 28-day targets of weekly
  origins overlap. A lag of 8 is reported as a robustness check.
- Clark-West test of the full model against B3 (nested), one-sided.
- Diebold-Mariano with the Harvey-Leybourne-Newbold small-sample correction
  against B0, B1 and B2 (non-nested).
- Out-of-sample R squared against each benchmark.
- A block bootstrap that resamples whole winters, for intervals on the slope
  and on the out-of-sample R squared.
- Holm correction across the secondary tests (H2, H3a, H3b, N1).
- Three crisis variants, all reported: full sample; 2021/22 and 2022/23
  excluded; full sample with a crisis-winter interaction on the slope.
- Robustness variant "explanatory, realised controls": every control is
  replaced by its value realised over the 28-day target window: French
  nuclear, Swiss nuclear, German wind (onshore plus offshore), and CH and
  DE HDD. Realised target-window HDD also replaces the climatological HDD.
  Month dummies are unchanged. B3 and the full model use these same
  controls in this variant. This variant uses
  information that is not available at the origin, so it is **not a
  forecast** and is reported only to show how much of the effect survives
  once the realised fundamentals of the window are known.

## 5. No-edge rule

There is no edge if any of these holds:

1. Clark-West p is 0.05 or higher, or the out-of-sample R squared against B3 is
   zero or below.
2. The 95% interval of the slope sits entirely inside the equivalence band of
   plus or minus EUR 2/MWh per 10 points, which is plus or minus EUR 0.2/MWh
   per point (TOST at 5%). This is the smallest effect of interest.
3. The effect disappears without the crisis winters 2021/22 and 2022/23, or
   the full model beats B3 out of sample in fewer than 3 of the 5 test
   winters (2021/22 to 2025/26).
   - The effect disappears if, in the crisis-excluded variant (test winters
     2023/24, 2024/25 and 2025/26), the out-of-sample R squared against B3 is
     zero or below, or the slope sign is opposite to the full-sample slope.
   - In the crisis-excluded variant the full model must also beat B3 out of
     sample in at least 2 of the 3 test winters.
   - This variant is a direction check, not a significance test, because 3
     test winters give too little power.

## 6. Secondary hypotheses (exploratory, Holm-corrected)

- H2: late-winter (March to April) CH minus IT-North spread responds to the
  same deviation.
- H3a (hydrology): the 1 May snow forecast (Part C) predicts the
  end-of-season fill.
- H3b (price): the 1 May forecast fill deviation predicts the mean
  October to December CH minus DE-LU spread.
- N1: a satellite nowcast (Part A) predicts the next SFOE release.

## 7. Already known before the freeze (SFOE only, no prices)

- Timing ceiling (`reports/results.md`): the standard deviation of the weekly
  change in the deviation, November to April, scaled to a 4-day head start and
  multiplied by the smallest effect of interest, gives EUR 0.17/MWh (linear) and
  EUR 0.23/MWh (square root). A satellite head start on the SFOE release is
  therefore unlikely to be worth anything on its own; Part A is framed as
  per-reservoir detail, and N1 stays exploratory.

## 8. Limitations

- SFOE revises its data and publishes no vintages. The backtest uses the
  current, revised series, so the historical predictor may differ slightly
  from what was visible on each release day.
- The same applies to the controls: ENTSO-E generation data can be revised
  after publication, and the latest days of ERA5-Land are preliminary
  (ERA5-Land-T) when first published. The backtest uses current values.

## 9. Live check

Winter 2026/27 (origins from November 2026 to April 2027) is reported
separately as a live out-of-sample result, using known_time from the release
log. It does not enter the no-edge rule, which is decided on the 5 test
winters 2021/22 to 2025/26 only.

## 10. Commitment

Every pre-registered test above is reported, significant or not, in
`reports/results.md`. Any change after the freeze is listed with its date and
reason in a "Deviations from the pre-registration" section.
