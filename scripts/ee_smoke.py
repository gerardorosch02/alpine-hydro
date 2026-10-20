"""Earth Engine smoke test: uv run --extra satellite python scripts/ee_smoke.py"""

import ee

from alpinehydro.config import secret

ee.Initialize(project=secret("EE_PROJECT"))
dix = ee.Geometry.Point(7.40, 46.08)  # Lac des Dix, approximate
s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(dix)
img = s2.filterDate("2026-06-01", "2026-11-01").sort("CLOUDY_PIXEL_PERCENTAGE").first()
print("Sentinel-2 over Lac des Dix:", ee.Date(img.get("system:time_start")).format().getInfo())
