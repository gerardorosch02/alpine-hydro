"""The summary table at the top of reports/results.md only repeats numbers from below it."""

import re
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "reports" / "results.md"

# A number with an optional sign (ASCII or Unicode minus), decimals, or a winter like 2026/27.
NUMBER = re.compile(r"(?<![\w./−+-])[−+]?\d+(?:\.\d+)?(?:/\d+)?(?![\w.]?\d)")


def _sections() -> tuple[list[str], str]:
    text = RESULTS.read_text(encoding="utf-8")
    start = text.index("## Summary of results")
    end = text.index("\n## ", start + 1)
    rows = [line for line in text[start:end].splitlines() if line.startswith("| ")]
    return rows[1:], text[end:]


def _numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def test_summary_has_one_row_per_claim():
    rows, _ = _sections()
    assert len(rows) == 9


def test_every_summary_number_appears_in_the_detailed_sections():
    rows, detail = _sections()
    detail_numbers = set(_numbers(detail))
    missing = [
        (row.split("|")[1].strip(), n)
        for row in rows
        for n in _numbers(row)
        if n not in detail_numbers
    ]
    assert not missing, missing


def test_number_pattern_keeps_signs_and_skips_identifiers():
    assert _numbers("slope −7.72 and +0.175, H3a, v0.1-prereg, R² 0.695, winter 2026/27") == [
        "−7.72",
        "+0.175",
        "0.695",
        "2026/27",
    ]
