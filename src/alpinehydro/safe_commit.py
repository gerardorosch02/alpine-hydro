"""Commit only the files the weekly run is allowed to change, or nothing at all.

Used by scripts/weekly.ps1 after `alpinehydro weekly`. File ownership is split so the two
jobs never commit the same file:

- the keyless GitHub Action (sfoe-check.yml) owns ACTION_OWNED: the SFOE tables, the
  release and PDF logs, and the hero chart. The laptop only reads them; any local change
  the weekly run makes to them is discarded before committing;
- the laptop job owns ALLOWLIST.

If any other modified, deleted or new (untracked, not ignored) file remains, nothing is
staged or committed and the reason is returned, so the laptop task can never commit
anything else.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

ALLOWLIST = [
    "data/processed/snow/*",
    "data/processed/live_forecasts.csv",
    "reports/figures/snow_tracker.png",
    "reports/figures/live_forecasts.png",
    "reports/weekly_log.md",
]
ACTION_OWNED = [
    "data/processed/sfoe*",
    "reports/figures/hero_storage.png",
    "reports/figures/hero_storage.svg",
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


def action_owned(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in ACTION_OWNED)


def discard_action_owned(repo: Path) -> list[str]:
    """Undo local changes to files the Action owns: restore tracked ones, delete new ones."""
    paths = [p for p in changed_paths(repo) if action_owned(p)]
    if not paths:
        return []
    tracked = set(_git(repo, "ls-files", "--", *paths).splitlines())
    _git(repo, "reset", "-q", "--", *paths)  # unstage, in case anything was staged
    for p in paths:
        if p in tracked:
            _git(repo, "checkout", "HEAD", "--", p)
        else:
            (repo / p).unlink(missing_ok=True)
    return paths


def commit(repo: Path, message: str) -> dict:
    """Discard Action-owned changes, then commit the allowed changes, or abort if anything
    else changed."""
    discarded = discard_action_owned(repo)
    paths = changed_paths(repo)
    if not paths:
        return {"committed": False, "reason": "nothing changed", "discarded": discarded}
    bad = [p for p in paths if not allowed(p)]
    if bad:
        return {
            "committed": False,
            "reason": "aborted: files outside the allowlist changed: " + ", ".join(bad),
            "discarded": discarded,
        }
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", message)
    head = _git(repo, "rev-parse", "HEAD").strip()
    return {"committed": True, "paths": paths, "commit": head, "discarded": discarded}
