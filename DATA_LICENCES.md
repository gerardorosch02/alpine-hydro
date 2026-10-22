# Data licences

The code is MIT licensed (see LICENSE). Data keep the licence of their source.

Rule for this repo: no raw imagery, no raw licensed data and no price series are
committed. What is committed is derived: regional means, curves, fitted values and
summary statistics, each credited below. Every term below was rechecked on its official
page on **2026-10-22**.

## Sources used

| Source | Used for | Terms (page, checked 2026-10-22) | Credit line | What we publish (derived only) |
|---|---|---|---|---|
| SFOE ogd17 weekly storage and weekly PDF ("Montagswerte") | Storage by region, validation, live weeks | opendata.swiss "Open use. Must provide the source." (`terms_by`), commercial use allowed. [ogd17 entry](https://opendata.swiss/en/dataset/enstat-fullungsgrad-der-speicherseen-sonntag-24h-wochenbericht-speicherinhalt), [terms](https://opendata.swiss/en/terms-of-use) | Source: Swiss Federal Office of Energy SFOE | Weekly storage tables in `data/processed/sfoe_*.csv` and the release and PDF logs. Not the PDF itself, and not its Rhine flow columns (BAFU) |
| SFOE dam register, SFOE 2025 reservoir list, SFOE 1983 "Speicherseen der Schweiz" | Reservoir levels, volumes and energy coefficients | Dam register on opendata.swiss: `terms_by`, as above. The two lists are SFOE publications on pubdb.bfe.admin.ch | Source: Swiss Federal Office of Energy SFOE | Single facts per reservoir in `config/reservoirs.yaml` |
| ENTSO-E Transparency Platform | Day-ahead prices (art. 12.1.d), generation per type (art. 16.1.b and c) for the H1 controls | Terms of Use approved 29 March 2023, applicable from 1 November 2023; list of data for free re-use, last modified 18 October 2023. [Legal terms page](https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions). **Neither item is on the free re-use list.** See the open item below | ENTSO-E Transparency Platform | No price or generation series. Derived: 11 yearly mean spreads (`data/processed/snow/h3b_q4_spread.csv`), fitted statistics in `reports/checks/h1_results.json`, the H1 and H3b figures, 28-day mean controls and (from November 2026) one realised mean spread per window in `data/processed/live_forecasts.csv` |
| SMARD (Bundesnetzagentur) | Cross-check of ENTSO-E prices only (results, Step 0) | CC BY 4.0. [smard.de/home/datennutzung](https://www.smard.de/home/datennutzung) | Bundesnetzagentur \| SMARD.de | Agreement statistics only, `reports/checks/smard_vs_entsoe.json`. No price series |
| Copernicus Sentinel-2 (`COPERNICUS/S2_SR_HARMONIZED`) | Water masks, Part A | Copernicus Sentinel Data Terms and Conditions (free, full and open). [Legal notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) | Contains modified Copernicus Sentinel data 2017-2026 | Per-scene levels and flags in `data/processed/satellite/`. No imagery |
| Cloud Score+ S2 (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`) | Sentinel-2 cloud screening | CC BY 4.0. [Catalogue page](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED) | Cloud Score+: Pasquarella et al. (2023), Google | Nothing directly; it only decides which scenes are clear |
| Landsat 8 and 9 Collection 2 Level-2 (USGS) | Water masks, Part A | Public domain; USGS asks for acknowledgement. [USGS data citation](https://www.usgs.gov/centers/eros/data-citation) | Landsat imagery courtesy of the U.S. Geological Survey | Per-scene levels and flags. No imagery |
| swisstopo swissTLM3D, swissALTI3D, swissSURFACE3D, swissBOUNDARIES3D | Lake and canton outlines, 2 m terrain, lidar flight dates | Free geodata: may be used, distributed and processed, also commercially; source reference mandatory. [swisstopo terms](https://www.swisstopo.admin.ch/en/terms-of-use-free-geodata-and-geoservices) | Source: Federal Office of Topography swisstopo | Outlines in `data/external/outlines/`, curves in `data/processed/hypsometry/`, survey dates in `reports/checks/`. No tiles |
| NASA SRTM v3 (`USGS/SRTMGL1_003`) | 30 m terrain below the swissALTI3D floor | US public domain. [Catalogue page](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003) | SRTM: NASA/USGS, public domain (Farr et al. 2007) | Derived curves only |
| Copernicus DEM GLO-30 (`COPERNICUS/DEM/GLO30_2024_1`) | 30 m terrain below the floor; elevation bands, Part C | Licence for the use of the Copernicus WorldDEM-30 (free). [Catalogue page](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30_2024_1) | Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30 | Derived curves; band polygons on the 500 m MODIS grid |
| JAXA ALOS AW3D30 v4.1 | 30 m surface model, compared only, never chosen | JAXA research data policy: free, derived products may be redistributed with credit. [JAXA policy](https://earth.jaxa.jp/en/data/policy/) | Credit: AW3D30 (JAXA) | Its offset and RMSE in `reports/checks/curves_global_dem.json` |
| JRC Global Surface Water v1.4 (`JRC/GSW1_4/GlobalSurfaceWater`) | Cross-check of the lake outlines | Copernicus Programme, free without restriction; cite the dataset and paper. [Catalogue page](https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater) | Source: EC JRC/Google. Pekel et al. (2016), Nature 540, 418-422 | Overlap statistics in `reports/checks/outlines_jrc.json` |
| ERA5-Land daily (Earth Engine `ECMWF/ERA5_LAND/DAILY_AGGR`, and the CDS "ERA5-Land daily statistics" for live HDD) | Lake-ice flag, snow water equivalent, H1 HDD controls, follow-up temperature and precipitation | Copernicus product licence, CC BY 4.0 on the CDS since 2 July 2025. [CDS licence](https://cds.climate.copernicus.eu/licences/cc-by), [CDS terms of use](https://cds.climate.copernicus.eu/disclaimer-privacy), [catalogue page](https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR) | Contains modified Copernicus Climate Change Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains. Muñoz Sabater (2019) | Frost-day counts in `scenes.csv`; regional daily means in `data/processed/snow/`; 28-day mean HDD in `live_forecasts.csv` |
| LSIB 2017 simplified (`USDOS/LSIB_SIMPLE/2017`) | Country outlines for the HDD controls | US public domain, no restrictions. [Catalogue page](https://developers.google.com/earth-engine/datasets/catalog/USDOS_LSIB_SIMPLE_2017) | United States Department of State, Office of the Geographer | Nothing; used only inside Earth Engine and the CDS crop |
| MODIS MOD10A1 and MYD10A1 v6.1 (NASA NSIDC DAAC) | Daily snow cover, Part C and the tracker | NASA data are open; citing the data set is a condition of use. [NSIDC MOD10A1](https://nsidc.org/data/mod10a1/versions/61), [NASA data use](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance) | Hall, D. K. and Riggs, G. A. (2021). MODIS/Terra Snow Cover Daily L3 Global 500m SIN Grid (MOD10A1, Version 61), doi:10.5067/MODIS/MOD10A1.061; and MODIS/Aqua (MYD10A1, Version 61), doi:10.5067/MODIS/MYD10A1.061. NSIDC DAAC | Regional daily means, `data/processed/snow/modis_daily.csv`. No imagery |
| VIIRS VJ210A1 v2, NOAA-21 (NASA NSIDC DAAC) | MODIS fallback for the snow tracker | As MODIS. [NSIDC VJ210A1](https://nsidc.org/data/vj210a1/versions/2) | Riggs, G. A. and Hall, D. K. (2026). VIIRS/JPSS2 Snow Cover Daily L3 Global 375m SIN Grid (VJ210A1, Version 2), doi:10.5067/IX3NQYYS3MOV. NSIDC DAAC | Regional daily means and the fit, `data/processed/snow/viirs_vj210a1_daily.csv`, `fallback_choice.json`. Granules deleted after cropping |
| GLIMS Glacier Database v1 (`GLIMS/20230607`), Swiss outlines from the Swiss Glacier Inventory SGI2016 (GLAMOS) | Glacier share per canton, follow-up (post-hoc) | Free use with citation. [NSIDC-0272](https://nsidc.org/data/nsidc-0272/versions/1); SGI2016 is CC BY 4.0 at [GLAMOS](https://doi.glamos.ch/data/inventory/inventory_sgi2016_r2020.html) | GLIMS Consortium et al. (2005). GLIMS Glacier Database (NSIDC-0272, Version 1), doi:10.7265/N5V98602. Linsbauer et al. (2021), The new Swiss Glacier Inventory SGI2016, Frontiers in Earth Science 9, doi:10.3389/feart.2021.704189 | Four area numbers, `data/processed/snow/followup_glacier_share.json`. No outlines |

Reservoir facts were also cross-checked against swissdams.ch and Wikipedia. Only single
facts (a volume, a level) are cited from them, in `config/reservoirs.yaml`.

## Considered but not used

Checked with `git grep` on 2026-10-22: nothing in `src/`, `config/`, `scripts/` or
`.github/` downloads these, and no committed result comes from them.

- DAHITI altimetry (DGFI-TUM): a private level check in weekend 2. No DAHITI data or
  result was committed or reported; the client code was removed in weekend 6.
- Copernicus Sentinel-1, Copernicus HR-S&I and HR-WSI, Suomi NPP VIIRS VNP10A1.
- MeteoSwiss, SLF (snow stations, SPASS, OSHD), Swissgrid, BAFU river flows.
- Energy-Charts, EEX, JAO.

## Open items

- **ENTSO-E reuse terms are unclear for what we publish.** Clause 3.1 of the Terms of
  Use allows use "for any purpose whatsoever" with credit, but the user must not
  prejudice the copyright or related rights of the Primary Owner of Data, and must seek
  that owner's agreement where there is a risk of doing so. Only items on the free
  re-use list (CC BY 4.0) are cleared without that agreement. Day-ahead prices (12.1.d)
  and generation per type (16.1.b and c) are not on the list. The terms do not say
  whether summary statistics derived from unlisted items (11 yearly means, 28-day means,
  regression results, scatter plots) count as re-use. **Decision needed from the owner
  before the repo goes public.**
- **Copernicus CDS terms change on 28 October 2026** (ECMWF forum notice of 5 October
  2026: Article 1 of the CDS Terms of Use is updated; continued use counts as
  acceptance). Recheck after 28 October 2026 that the ERA5-Land licence and credit line
  above are unchanged.
- The ogd17 entry on opendata.swiss now lists the CSV at `www.bfe-ogd.ch`; the pipeline
  still reads the older `uvek-gis.admin.ch` address, which worked on 2026-10-22.
