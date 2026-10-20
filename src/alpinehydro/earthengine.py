"""Earth Engine start-up. `ee` is imported inside functions only (CI has no login)."""

from __future__ import annotations

from alpinehydro import config

_ready = False


def init() -> None:
    """Initialise Earth Engine once, with the project from EE_PROJECT."""
    global _ready
    if _ready:
        return
    import ee

    ee.Initialize(project=config.secret("EE_PROJECT"))
    _ready = True
