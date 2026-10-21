import subprocess

import pandas as pd
import pytest

from alpinehydro import live, safe_commit, weekly_run

# ---------------------------------------------------------------- weekly run


def _steps(state):
    """Fake steps that write a file only when the 'source' has something new."""

    def sfoe(ctx):
        target = state["dir"] / "sfoe.csv"
        text = f"latest,{state['latest']}\n"
        if target.exists() and target.read_text() == text:
            return {"changed": False, "summary": "nothing new"}
        target.write_text(text)
        return {"changed": True, "summary": f"latest {state['latest']}"}

    return {"SFOE values": sfoe}


def test_weekly_is_safe_to_run_twice(tmp_path):
    state = {"dir": tmp_path, "latest": "2026-11-01"}
    log = tmp_path / "weekly_log.md"
    figs = []

    def make_figures():
        figs.append(1)
        return []

    r1 = weekly_run.run(_steps(state), make_figures, log, echo=lambda m: None)
    assert r1["changed"] and len(figs) == 1
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    r2 = weekly_run.run(_steps(state), make_figures, log, echo=lambda m: None)
    assert not r2["changed"] and len(figs) == 1  # no figures, no log entry
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == first

    state["latest"] = "2026-11-08"
    r3 = weekly_run.run(_steps(state), make_figures, log, echo=lambda m: None)
    assert r3["changed"]
    text = log.read_text()
    assert text.startswith("# Weekly live log")
    assert text.count("## Run of") == 2
    assert text.index("2026-11-08") < text.index("2026-11-01")  # newest first


def test_failing_step_is_logged_and_others_still_run(tmp_path):
    def boom(ctx):
        raise RuntimeError("network down")

    ran = []
    steps = {"a": boom, "b": lambda ctx: ran.append(1) or {"changed": False, "summary": "ok"}}
    r = weekly_run.run(steps, lambda: [], tmp_path / "log.md", echo=lambda m: None)
    assert ran == [1]
    assert any("a failed: RuntimeError: network down" in w for w in r["warnings"])


def test_tracker_without_choice_uses_modis_only(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly_run, "CHOICE", tmp_path / "none.json")
    modis = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-10-01"), "region": r, "band_m": 1800, "fsc": 0.1}
            for r in ["Wallis", "Graubuenden", "Tessin", "Total"]
        ]
    )
    t = weekly_run.build_tracker(modis, pd.Timestamp("2026-10-21"), viirs_loader=None)
    assert set(t["source"]) == {"modis", "missing"}
    assert pd.Timestamp(t["date"].min()) == pd.Timestamp("2026-10-01")


# ---------------------------------------------------------------- realised spreads


def _table(path, target_start, target_end, realised=""):
    row = {c: "" for c in live.COLUMNS}
    row.update(
        valid_sunday="2026-11-01",
        target_start=target_start,
        target_end=target_end,
        forecast_full=5.0,
        forecast_b3=4.0,
        realised_spread=realised,
    )
    live._write(pd.DataFrame([row]), path)


def test_realised_spread_only_after_the_window_and_with_all_days(tmp_path):
    path = tmp_path / "live.csv"
    _table(path, "2026-11-07", "2026-12-04")
    days = pd.date_range("2026-11-07", "2026-12-04")
    spread = pd.Series(2.0, index=days)

    r = live.fill_realised(spread, pd.Timestamp("2026-12-04"), path)  # last day not passed
    assert r["filled"] == [] and not r["changed"]

    r = live.fill_realised(spread.iloc[:-1], pd.Timestamp("2026-12-05"), path)  # a day missing
    assert r["waiting_for_prices"] == ["2026-11-01"] and not r["changed"]

    r = live.fill_realised(spread, pd.Timestamp("2026-12-05"), path)
    assert r["filled"] == ["2026-11-01"]
    assert live.load(path)["realised_spread"].iloc[0] == "2.00"

    before = path.read_bytes()
    r = live.fill_realised(spread * 3, pd.Timestamp("2026-12-20"), path)  # never overwritten
    assert r["filled"] == [] and path.read_bytes() == before


# ---------------------------------------------------------------- safe commit


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for p in ["data/processed/sfoe_storage_merged.csv", "reports/weekly_log.md", "README.md"]:
        f = tmp_path / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("v1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_safe_commit_commits_only_allowlisted_files(repo):
    (repo / "data/processed/sfoe_storage_merged.csv").write_text("v2\n")
    (repo / "reports/weekly_log.md").write_text("v2\n")
    (repo / "reports/figures").mkdir(parents=True)
    (repo / "reports/figures/live_forecasts.png").write_bytes(b"png")
    r = safe_commit.commit(repo, "weekly")
    assert r["committed"]
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_safe_commit_blocks_when_any_other_file_changed(repo):
    head = _head(repo)
    (repo / "data/processed/sfoe_storage_merged.csv").write_text("v2\n")
    (repo / "README.md").write_text("edited\n")
    r = safe_commit.commit(repo, "weekly")
    assert not r["committed"]
    assert "README.md" in r["reason"]
    assert _head(repo) == head
    assert _git(repo, "diff", "--cached", "--name-only").stdout == ""  # nothing staged


def test_safe_commit_blocks_new_untracked_file_outside_list(repo):
    (repo / "reports/weekly_log.md").write_text("v2\n")
    (repo / "notes.txt").write_text("x\n")
    r = safe_commit.commit(repo, "weekly")
    assert not r["committed"] and "notes.txt" in r["reason"]


def test_safe_commit_nothing_changed(repo):
    assert safe_commit.commit(repo, "weekly") == {"committed": False, "reason": "nothing changed"}


def test_allowlist_patterns():
    assert safe_commit.allowed("data/processed/sfoe_pdf_log.csv")
    assert safe_commit.allowed("data/processed/snow/tracker_daily.csv")
    assert safe_commit.allowed("data/processed/live_forecasts.csv")
    assert not safe_commit.allowed("data/processed/hypsometry/x.csv")
    assert not safe_commit.allowed("src/alpinehydro/cli.py")
    assert not safe_commit.allowed("reports/results.md")
