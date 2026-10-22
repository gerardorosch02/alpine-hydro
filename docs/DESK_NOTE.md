# Desk note: Swiss storage and the CH minus DE premium

One page for a trader. Every number comes from [reports/results.md](../reports/results.md).
This is research, not a trading recommendation.

## What the project measures

- **Storage deviation.** Swiss reservoir fill (SFOE, weekly) minus the median of the
  same week over the previous 10 years, in points of capacity, as known on release day.
- **The premium.** The mean daily CH minus DE-LU day-ahead baseload spread over the
  28 days after the release.
- **Snow.** Daily MODIS snow cover at or above 1800 m in Wallis, Graubuenden and Tessin,
  as a forecast of how full the Alpine reservoirs end the summer.

## What the evidence says

**The link is real in stress winters.** Over 2015/16 to 2025/26, storage 10 points
below normal went with a CH minus DE-LU spread about 7.7 EUR/MWh higher over the next
28 days (slope −7.72 per 10 points, 95% interval −13.19 to −2.25). The sign is the
expected one and it survives knowing the window's realised nuclear, wind and
temperature (−9.20 per 10 points).

**But the 2021/22 and 2022/23 crisis winters carry most of it.** In those winters the
slope is −14.33 per 10 points; outside them it is −4.40. Without them the slope is
−3.58.

**It does not forecast out of sample.** Against a model that already knows recent
nuclear output, wind and heating demand, adding storage improved the forecast by almost
nothing (out-of-sample R² 0.009). Without the crisis winters it beat that model in only
1 of 3 test winters. Under the rule fixed before the test, the verdict is **no edge**.

**Snow does not add to the refill forecast.** 1 May snow cover pointed the right way
(skill +0.175 against starting storage alone), but 15 test years cannot tell that from
luck (Holm p 0.268). In 2026 the 1 May forecast was 82.6% full at the end of September
against an actual 74.0%: the drought came in summer, after the snow reading. A post-hoc
1 July update did not help either (skill +0.012).

**2026 was a weather story, not an operator story (post-hoc water balance).** From April to August less water came in than in any year since 2015 (about 2,600 GWh below normal) and operators released about 2,300 GWh less, not more, so the snow forecast missed the water.

**Snow and the autumn premium: too few years.** Lower forecast fill went with a higher
October to December premium (−36.9 EUR/MWh per 10 points), but with 11 years the
smallest effect the test could detect is 54.5, and the result is not significant after
correction (Holm p 0.058).

## What to watch this winter

- **The storage deviation.** On 27 September 2026 Swiss storage was 74.1% full,
  −11.2 points against the 10-year norm, and below the 2000 to 2025 minimum for that
  week every week from 5 July. The hero chart in the README is updated each week.
- **The snow tracker** ([figure](../reports/figures/snow_tracker.png)): daily snow cover
  against 2000 to 2025, by region.
- **The live forecast table** ([results](../reports/results.md#live-check-202627),
  [figure](../reports/figures/live_forecasts.png)): one forecast of the next 28-day
  spread per SFOE week from the week of Sunday 1 November 2026, with the realised spread
  added once each window has passed. It is scored only after April 2027.

## Main caveats

- Only about 11 winters of free prices, and two of them are the gas crisis.
- The published storage number is public and known to the market. A few days'
  satellite head start on it is worth about EUR 0.17 to 0.23/MWh at most.
- End-of-season fill is inflow minus what operators chose to generate, so it is not
  pure hydrology.
- No forward prices were used, so nothing here says whether the signal is already
  priced in.
