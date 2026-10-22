# Weekly live run for alpine-hydro (Windows Task Scheduler, Wednesdays 18:00).
#
# 1. Refuses to start unless the repo is on main with a clean working tree, so your own
#    unfinished work is never touched or committed.
# 2. Pulls (fast-forward only) to pick up the SFOE commits made by the GitHub Action.
# 3. Runs `uv run alpinehydro weekly` (keys come from .env or the Windows environment).
# 4. Commits only the laptop-owned derived files (alpinehydro safe-commit). Changes to
#    files the GitHub Action owns (SFOE tables and logs, hero chart) are discarded first.
#    If any other file changed, nothing is committed and the reason is logged.
# 5. Pushes. If the push is rejected, rebases once on origin/main and tries again. If the
#    rebase hits any conflict it is aborted, the clean state is checked, the reason is
#    logged and the script exits with code 4; the repo is never left mid-rebase.
#
# -NoPush: do everything except the push (for a manual test run).
# Every run writes data/interim/logs/weekly_<date>_<time>.log (git-ignored).

param([switch]$NoPush)

$ErrorActionPreference = "Stop"
# The repo is the parent of this script's folder. uv and git are found on PATH; set
# ALPINEHYDRO_UV or ALPINEHYDRO_GIT to a full path if the scheduled task cannot see them.
$Repo = Split-Path -Parent $PSScriptRoot

Set-Location $Repo
$LogDir = Join-Path $Repo "data\interim\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir ("weekly_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmm"))

function Write-Log([string]$Text) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

# Runs a native command through cmd so its stdout and stderr go to the log as plain text.
function Invoke-Logged([string]$Exe, [string]$Arguments) {
    $cmd = '"{0}" {1} >> "{2}" 2>&1' -f $Exe, $Arguments, $Log
    cmd.exe /d /c $cmd
    return $LASTEXITCODE
}

Write-Log "start"

try {
    $Uv = if ($env:ALPINEHYDRO_UV) { $env:ALPINEHYDRO_UV } else { (Get-Command uv.exe).Source }
    $Git = if ($env:ALPINEHYDRO_GIT) { $env:ALPINEHYDRO_GIT } else { (Get-Command git.exe).Source }
} catch {
    Write-Log "aborted: uv or git not found on PATH (set ALPINEHYDRO_UV or ALPINEHYDRO_GIT); nothing run"
    exit 1
}

$gitDir = (& $Git rev-parse --absolute-git-dir).Trim()
if ((Test-Path (Join-Path $gitDir "rebase-merge")) -or (Test-Path (Join-Path $gitDir "rebase-apply")) -or (Test-Path (Join-Path $gitDir "MERGE_HEAD"))) {
    Write-Log "aborted: a rebase or merge is in progress in the repo; nothing run"
    exit 1
}

$branch = (& $Git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") {
    Write-Log "aborted: the repo is on branch '$branch', not main; nothing run"
    exit 1
}
$dirty = & $Git status --porcelain
if ($dirty) {
    Write-Log "aborted: the working tree is not clean before the run; nothing run. Changed:"
    $dirty | ForEach-Object { Write-Log "  $_" }
    exit 1
}

if ((Invoke-Logged $Git "pull --ff-only origin main") -ne 0) {
    Write-Log "aborted: git pull --ff-only failed (local main has diverged?); nothing run"
    exit 1
}

$code = Invoke-Logged $Uv "run alpinehydro weekly"
Write-Log "alpinehydro weekly exit code $code"

$msg = "Weekly live run {0}" -f (Get-Date -Format "yyyy-MM-dd")
$code = Invoke-Logged $Uv "run alpinehydro safe-commit -m `"$msg`""
if ($code -eq 3) {
    Write-Log "commit aborted by the allowlist (see the line above); nothing committed or pushed"
    exit 3
}
if ($code -ne 0) {
    Write-Log "safe-commit failed with exit code $code; nothing pushed"
    exit $code
}

$ahead = (& $Git rev-list --count origin/main..HEAD).Trim()
if ($ahead -eq "0") {
    Write-Log "nothing to push"
    Write-Log "done"
    exit 0
}
if ($NoPush) {
    Write-Log "-NoPush: $ahead local commit(s) not pushed"
    Write-Log "done"
    exit 0
}

if ((Invoke-Logged $Git "push origin main") -ne 0) {
    Write-Log "push rejected; rebasing once on origin/main"
    if ((Invoke-Logged $Git "pull --rebase origin main") -ne 0) {
        Invoke-Logged $Git "rebase --abort" | Out-Null
        $midRebase = (Test-Path (Join-Path $gitDir "rebase-merge")) -or (Test-Path (Join-Path $gitDir "rebase-apply"))
        $left = & $Git status --porcelain
        if ($midRebase -or $left) {
            Write-Log "rebase conflict, and the abort did not restore a clean state: fix by hand"
            exit 5
        }
        Write-Log "rebase conflict with origin/main: rebase aborted, tree clean; the weekly commit stays local and nothing was pushed. Resolve by hand (see the runbook)."
        exit 4
    }
    if ((Invoke-Logged $Git "push origin main") -ne 0) {
        Write-Log "second push failed; the commit stays local, push by hand"
        exit 4
    }
}
Write-Log "pushed"
Write-Log "done"
exit 0
