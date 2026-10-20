"""Load YAML settings and environment variables.

Secrets are read from the environment only. A local, git-ignored .env file is
loaded if present. Values are never printed or logged.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"


@lru_cache
def pipeline() -> dict[str, Any]:
    with open(CONFIG_DIR / "pipeline.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def reservoirs() -> list[dict[str, Any]]:
    with open(CONFIG_DIR / "reservoirs.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["reservoirs"]


def _load_env() -> None:
    # override=False keeps variables already set in the shell.
    load_dotenv(ROOT / ".env", override=False)


def secret(name: str) -> str:
    """Return a secret from the environment, or fail without revealing anything."""
    _load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Put it in a local .env file (see .env.example) "
            "or in your environment."
        )
    return value


def has_secret(name: str) -> bool:
    _load_env()
    return bool(os.environ.get(name, "").strip())
