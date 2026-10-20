# Reservoir outlines

Source: Federal Office of Topography swisstopo. swissTLM3D release 2026-02
(open data, free use with attribution), layer `TLM_STEHENDES_GEWAESSER`.
The shoreline lines of each lake are joined into one polygon by
`alpinehydro outlines`.

- `<slug>_outline.geojson`: the lake outline as mapped. Its height
  (`tlm_level_m`) is the water level on the mapping date, which is a few
  metres below full supply for most reservoirs.
- `<slug>_window.geojson`: the outline buffered by 300 m, the analysis window.

Both are EPSG:4326 (lon/lat), converted from LV95 (EPSG:2056) and rounded to
1e-6 degrees. The cross-check against JRC Global Surface Water max_extent is in
`reports/checks/outlines_jrc.json`. OpenStreetMap is not used (ODbL share-alike).
