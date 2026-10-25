<#
.SYNOPSIS
    Track B gate: run the real-QEMU contract tests inside WSL, honestly.

.DESCRIPTION
    Locates the patched qemu-system-xtensa ($env:WOSP_QEMU first, else the
    documented default: the sibling qemu-build checkout) and prints WHICH
    locator was used. Then runs, inside WSL with the repo already mounted
    (/mnt/<drive>/...), the exact command documented in README.md and
    SETUP.md (Track B):

        wsl -- bash -lc "cd '<repo>' && WOSP_QEMU='<qemu>' python3 -m pytest tests/test_qemu_monitor_qemu.py -v"

    The full pytest output (including the summary line) is printed verbatim.

    Exit codes - success is impossible to reach with a skipped test:
      0  every contract test RAN and passed (summary says "passed", no "skipped")
      1  WSL is missing or 'wsl --status' failed
      2  qemu-system-xtensa not found (path printed)
      3  pytest failed, skipped >=1 test, or the summary is not a clean pass

    No Set-Content / file writes anywhere; this script only runs commands.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\run_emulator_tests.ps1
#>

$ErrorActionPreference = "Continue"  # native stderr must never abort the script (see setup.ps1)

$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# ---- 1. WSL present and functional? ------------------------------------
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Host "[FAIL] wsl not found on PATH - install WSL2 first (SETUP.md Part A)" -ForegroundColor Red
    exit 1
}
# wsl --status prints UTF-16 (NUL between chars) when captured; strip NULs
# so the version banner is readable.
$wslStatus = ((& wsl --status 2>&1 | Out-String) -replace "`0", "")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 'wsl --status' exited $LASTEXITCODE - WSL is not available:" -ForegroundColor Red
    Write-Host $wslStatus
    exit 1
}
Write-Host "[ ok ] wsl --status (exit 0)"
$statusHead = ($wslStatus -split "`r?`n" | Where-Object { $_ -ne "" } | Select-Object -First 2)
foreach ($l in $statusHead) { Write-Host "       $l" }

# ---- 2. Locate qemu-system-xtensa (print which locator won) -----------
$qemu = $env:WOSP_QEMU
$locator = "`$env:WOSP_QEMU"
if (-not $qemu) {
    # Documented default: sibling qemu-build checkout (README/SETUP Track B).
    $qemu = Join-Path (Split-Path -Parent $Repo) "qemu-build\qemu-esp_develop_9.2.2_20260417\build\qemu-system-xtensa"
    $locator = "documented default (sibling qemu-build checkout)"
}
Write-Host "[ .. ] locator        : $locator"
Write-Host "       binary path   : $qemu"
if (-not (Test-Path $qemu)) {
    Write-Host "[FAIL] qemu-system-xtensa not found (locator: $locator)" -ForegroundColor Red
    Write-Host "       Set `$env:WOSP_QEMU to the patched binary, or build it per SETUP.md Part E." -ForegroundColor Red
    exit 2
}
Write-Host "[ ok ] binary exists"

# ---- 3. Convert to WSL paths (repo + binary) ---------------------------
$repoDrive  = $Repo.Substring(0, 1).ToLower()
$repoRest   = $Repo.Substring(2).Replace('\', '/')
$repoWsl    = "/mnt/$repoDrive$repoRest"
$qemuDrive  = $qemu.Substring(0, 1).ToLower()
$qemuRest   = $qemu.Substring(2).Replace('\', '/')
$qemuWsl    = "/mnt/$qemuDrive$qemuRest"

# ---- 4. Run the documented command inside WSL --------------------------
$inner = "cd '$repoWsl' && WOSP_QEMU='$qemuWsl' python3 -m pytest tests/test_qemu_monitor_qemu.py -v"
Write-Host "[ .. ] wsl -- bash -lc `"$inner`""
$output = (& wsl -- bash -lc $inner 2>&1 | Out-String)
$rc = $LASTEXITCODE
Write-Host ""
Write-Host $output
Write-Host "---- pytest summary (last non-empty line) ----"
$lastLine = ($output -split "`r?`n" | Where-Object { $_ -ne "" } | Select-Object -Last 1)
Write-Host $lastLine

# ---- 5. Gate: skipped tests are NOT success ----------------------------
$low = $output.ToLower()
if ($rc -ne 0) {
    Write-Host "[FAIL] pytest exited $rc" -ForegroundColor Red
    exit 3
}
if ($low -match "skipped") {
    Write-Host "[FAIL] at least one contract test was SKIPPED - a skip is never a pass" -ForegroundColor Red
    exit 3
}
if ($low -notmatch "passed") {
    Write-Host "[FAIL] no 'passed' found in the pytest output - refusing to call this success" -ForegroundColor Red
    exit 3
}
Write-Host "[GATE] all contract tests ran and passed (0 skips)" -ForegroundColor Green
exit 0
