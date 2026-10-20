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

Links

- ENTSO-E Terms of Use and the open data list: https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions
- SMARD data use: https://www.smard.de/home/datennutzung
- SFOE ogd17 CSV: https://www.uvek-gis.admin.ch/BFE/ogd/17/ogd17_fuellungsgrad_speicherseen.csv
