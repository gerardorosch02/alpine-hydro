"""Commit only the files the weekly run is allowed to change, or nothing at all.

Used by scripts/weekly.ps1 after `alpinehydro weekly`. If any modified, deleted or new
(untracked, not ignored) file lies outside the allowlist, nothing is staged or committed
and the reason is returned, so the laptop task can never commit anything else.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

ALLOWLIST = [
    "data/processed/sfoe*",
    "data/processed/snow/*",
    "data/processed/live_forecasts.csv",
    "reports/figures/*",
    "reports/weekly_log.md",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def changed_paths(repo: Path) -> list[str]:
    """Every path git reports as changed, staged or untracked (ignored files excluded)."""
    out = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    paths, items = [], out.split("\0")
    i = 0
    while i < len(items):
        it = items[i]
        if not it:
            i += 1
            continue
        status, path = it[:2], it[3:]
        paths.append(path)
        if status[0] in "RC":  # a rename carries the old path as the next item
            i += 1
            paths.append(items[i])
        i += 1
    return sorted(set(paths))


def allowed(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in ALLOWLIST)


def commit(repo: Path, message: str) -> dict:
    """Stage and commit the allowed changes, or abort if anything else changed."""
    paths = changed_paths(repo)
    if not paths:
        return {"committed": False, "reason": "nothing changed"}
    bad = [p for p in paths if not allowed(p)]
    if bad:
        return {
            "committed": False,
            "reason": "aborted: files outside the allowlist changed: " + ", ".join(bad),
        }
    staged_before = _git(repo, "diff", "--cached", "--name-only").split()
    if any(not allowed(p) for p in staged_before):
        return {"committed": False, "reason": "aborted: something outside the list is staged"}
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", message)
    return {"committed": True, "paths": paths, "commit": _git(repo, "rev-parse", "HEAD").strip()}
