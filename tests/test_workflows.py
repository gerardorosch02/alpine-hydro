import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# Anything that would mean a key reaches CI, or a keyed service is called from CI.
FORBIDDEN = [
    r"secrets\.",
    r"ENTSOE",
    r"EE_PROJECT",
    r"EARTHDATA",
    r"CDSE_",
    r"API_KEY",
    r"PASSWORD",
    r"earthengine",
    r"\.env\b",
]
KEYED_COMMANDS = [
    "fetch-entsoe",
    "snow-series",
    "snow-outlines",
    "live-forecast",
    "fallback-evaluate",
    "alpinehydro weekly",
    "alpinehydro figures",
    "scenes",
    "masks",
]


def test_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"ci.yml", "sfoe-check.yml"} <= names


def test_no_keys_in_any_workflow():
    for p in WORKFLOWS:
        text = p.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            assert not re.search(pat, text, re.IGNORECASE), f"{p.name} matches {pat}"


def test_sfoe_check_runs_only_keyless_commands():
    text = (ROOT / ".github" / "workflows" / "sfoe-check.yml").read_text(encoding="utf-8")
    for cmd in KEYED_COMMANDS:
        assert cmd not in text, cmd
    runs = re.findall(r"uv run alpinehydro ([\w-]+)", text)
    assert set(runs) == {"log-release", "sfoe-update", "hero"}
    assert "ubuntu-24.04" in text and "ubuntu-latest" not in text
