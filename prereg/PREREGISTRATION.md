# Pre-registration: Swiss storage deviation and the CH minus DE-LU spread

Status: DRAFT, written 2026-10-20 (weekend 1). It will be frozen as git tag
`v0.1-prereg` on weekend 2, before any price model is run. No price slope,
price regression or price chart has been looked at while writing it. The only
price work so far is downloading, resampling and checking that two price
sources agree with each other.

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
- Target y: the mean of the daily CH minus DE-LU baseload spread (EUR/MWh) over
  the 28 delivery days that start with the delivery day of the first Swiss
  day-ahead auction held after known_time. The Swiss auction closes at 11:00
  Europe/Zurich for the next day, so a Thursday 23:59 known_time gives a
  Friday auction and a window that starts on Saturday. Daily baseload is the
  mean of the hours of the Europe/Zurich delivery day (23, 24 or 25 hours).
  DE-LU uses DE-AT-LU before 2018-10-01. Since 2025-10-01 coupled zones clear
  in 15-minute steps; all prices are averaged to hours first.
- Season: forecast origins whose valid Sunday falls in November to April.
- Controls: French nuclear availability, Swiss nuclear availability, heating
  degree days, German wind, and month dummies. Each control is taken as known
  at the forecast origin (forecast or last published value, no realised
  future values). Exact series and sources get fixed before the freeze.
- Outliers: y and x are winsorised at the 1st and 99th percentile, with the
  cut-offs estimated on the training window of each fold only.

### Sample

CH day-ahead prices on ENTSO-E are continuous from 2015-01-01 (DE-LU, FR and
IT-North from 2015-01-05; CH has only isolated days in 2014). The first full winter
is therefore 2015/16, and the 10-year norm is defined from 2010. With at least
6 training winters the first test winter is 2021/22.

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

- Newey-West (HAC) standard errors for the in-sample slope, with a lag length
  of at least 4 weeks because the 28-day targets overlap.
- Clark-West test of the full model against B3 (nested), one-sided.
- Diebold-Mariano with the Harvey-Leybourne-Newbold small-sample correction
  against B0, B1 and B2 (non-nested).
- Out-of-sample R squared against each benchmark.
- A block bootstrap that resamples whole winters, for intervals on the slope
  and on the out-of-sample R squared.
- Holm correction across the secondary tests (H2, H3, N1).
- Three crisis variants, all reported: full sample; 2021/22 and 2022/23
  excluded; full sample with a crisis-winter interaction on the slope.

## 5. No-edge rule

There is no edge if any of these holds:

1. Clark-West p is 0.05 or higher, or the out-of-sample R squared against B3 is
   zero or below.
2. The 95% interval of the slope sits entirely inside the equivalence band of
   plus or minus EUR 2/MWh per 10 points (TOST at 5%). This is the smallest
   effect of interest.
3. The effect disappears without the crisis winters 2021/22 and 2022/23, or
   the slope has the expected sign in fewer than 60% of test winters.

## 6. Secondary hypotheses (exploratory, Holm-corrected)

- H2: late-winter (February to April) CH minus IT-North spread responds to the
  same deviation.
- H3: snowpack (Part C) forecasts the end-of-season fill.
- N1: a satellite nowcast (Part A) predicts the next SFOE release.

## 7. Already known before the freeze (SFOE only, no prices)

- Timing ceiling (`reports/results.md`): the standard deviation of the weekly
  change in the deviation, November to April, scaled to a 4-day head start and
  multiplied by the smallest effect of interest, gives EUR 0.17/MWh (linear) and
  EUR 0.23/MWh (square root). A satellite head start on the SFOE release is
  therefore unlikely to be worth anything on its own; Part A is framed as
  per-reservoir detail, and N1 stays exploratory.

## 8. Commitment

Every pre-registered test above is reported, significant or not, in
`reports/results.md`. Any change after the freeze is listed with its date and
reason in a "Deviations from the pre-registration" section.
