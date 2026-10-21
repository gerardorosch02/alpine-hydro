# Data licences

The code is MIT licensed (see LICENSE). Data keep the licence of their source.
Rule for this repo: price data from ENTSO-E, Energy-Charts, EEX or JAO are never
committed, raw or processed. Only SFOE storage, SMARD-derived prices and my own
derived statistics may be committed, and no SMARD price series is committed yet.

| Source | What | Licence | Credit line | Committed |
|---|---|---|---|---|
| SFOE ogd17 | Weekly reservoir storage by region | opendata.swiss "terms_by": open use, commercial use allowed, source must be given (ogd17 catalogue entry) | Source: Swiss Federal Office of Energy SFOE | Yes: `data/processed/sfoe_storage_weekly.csv`, release and PDF logs |
| SFOE weekly PDF | Same storage, published earlier than the CSV | As above | Source: Swiss Federal Office of Energy SFOE | No (only headers and hash in `sfoe_pdf_log.csv`) |
| ENTSO-E Transparency Platform | Day-ahead prices (art. 12.1.d), reservoir filling (art. 16.1.d) | Terms of Use of 29 March 2023. Neither item is on the CC-BY 4.0 "List of data available for free re-use" (18 October 2023) | ENTSO-E Transparency Platform | No. Only summary statistics of my own checks |
| SMARD (Bundesnetzagentur) | Day-ahead prices DE-LU, CH, FR | CC BY 4.0 (smard.de/home/datennutzung, checked 2026-10-20) | Bundesnetzagentur \| SMARD.de | Not yet. Allowed, but kept in `data/interim/` until needed |
| Energy-Charts | Prices | Not used | n/a | No |
| EEX | Futures, auctions | Proprietary | n/a | No |
| JAO | Cross-border auctions | Not used yet | n/a | No |
| Copernicus Sentinel-2, Sentinel-1 | Imagery (Part A) | Copernicus open licence | Contains modified Copernicus Sentinel data [year] | Derived statistics only (weekend 2) |
| Landsat (USGS) | Imagery (Part A) | Public domain | Landsat imagery courtesy of the U.S. Geological Survey | Derived statistics only (weekend 2) |
| swisstopo swissTLM3D, swissALTI3D | Lake shorelines; 2 m terrain model | swisstopo open government data (free use, source must be given) | Source: Federal Office of Topography swisstopo | Outlines in `data/external/outlines/` and derived curves in `data/processed/hypsometry/`. No tiles |
| NASA SRTM v3 (USGS/SRTMGL1_003) | 30 m terrain, February 2000, below the swissALTI3D floor | Public domain (NASA/USGS) | SRTM: NASA/USGS, public domain | Derived curves only |
| Copernicus DEM GLO-30 (2024_1) | 30 m terrain, 2011 to 2015, below the swissALTI3D floor | Copernicus DEM licence (free use with attribution) | Produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved | Derived curves only |
| ERA5-Land daily (ECMWF/ERA5_LAND/DAILY_AGGR) | Daily mean 2 m temperature at each lake, for the ice_likely flag | Copernicus licence (free use with attribution) | Contains modified Copernicus Climate Change Service information (ERA5-Land) | Only the frost-day count per scene in `scenes.csv`; the series stays in `data/interim/era5/` |
| DAHITI (DGFI-TUM) | Altimetry water levels, a private check of Sihlsee | Free for noncommercial use with a personal key | DAHITI, DGFI-TUM (Schwatke et al. 2015) | No. Raw data in `data/raw/dahiti/`; only summary numbers in my private notes |
| JAXA ALOS AW3D30 v4.1 | 30 m surface model, 2006 to 2011, compared only (not chosen anywhere) | JAXA terms of use (free use with credit) | (c) JAXA | Nothing derived from it is used in a curve; its offset and RMSE appear in `reports/checks/curves_global_dem.json` |

Links

- ENTSO-E Terms of Use and the open data list: https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions
- SMARD data use: https://www.smard.de/home/datennutzung
- SFOE ogd17 CSV: https://www.uvek-gis.admin.ch/BFE/ogd/17/ogd17_fuellungsgrad_speicherseen.csv
