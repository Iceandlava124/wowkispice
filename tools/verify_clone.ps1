<#
.SYNOPSIS
    R1 as scored, one run: clone -> setup -> gate -> verify -> verdict.

.DESCRIPTION
    Real `git clone` of the committed branch into %TEMP% (--no-hardlinks, so
    the clone sees git objects only: no venv, no logs, no uncommitted work),
    then the four steps a fresh machine would take:

        1. CLONE   git clone --no-hardlinks -b <branch> <repo> <dest>
        2. SETUP   setup.ps1            (venv + pinned pypi + ngspice DLL)
        3. GATE    tools\run_tests.py   (full suite, output under logs\)
        4. VERIFY  run_selfcheck.bat    (exit code must be non-zero on FAIL)
        5. VERDICT PASS only when 1-4 all exited 0

    Nothing is copied from the dev tree, and the clone is NEVER edited:
    findings become jobs under the master rules instead of fixes here.
    Network is only what setup.ps1 itself uses (ngspice URL, pypi.org) -
    the approved hosts from owner decision 5.

    Exit code: 0 = verdict PASS, 1 = verdict FAIL, 2 = clone failed.
    The full transcript of every step is appended to logs\r1-verify.txt.
#>
param(
    [Parameter(Mandatory = $true)][int]$RunId,
    [string]$Branch = 'baseline-fix',
    [string]$Repo = '',
    [string]$TempRoot = ([IO.Path]::GetTempPath()),
    [switch]$KeepClone
)
$ErrorActionPreference = 'Continue'
# $PSScriptRoot is empty while param defaults are evaluated in PS 5.1, so the
# repo root is resolved after binding.
if (-not $Repo) { $Repo = Split-Path -Parent $PSScriptRoot }
$Clone = Join-Path $TempRoot ("wosp-r1-{0}" -f $RunId)
$Transcript = Join-Path (Join-Path $Repo 'logs') 'r1-verify.txt'
$Progress = Join-Path (Join-Path (Join-Path $Repo 'logs') 'cmd') 'r1-verify.progress'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Transcript) | Out-Null

function Mark([string]$m) {
    $line = "{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Add-Content -Path $Progress -Value $line
    Write-Host $line
}
function Record([string]$m) {
    Add-Content -Path $Transcript -Value ("RUN{0} {1}" -f $RunId, $m)
}

Mark ("=== RUN {0} START clone={1} ===" -f $RunId, $Clone)
Record ("=== {0} branch={1} ===" -f (Get-Date -Format o), $Branch)

# ---- 1. CLONE -----------------------------------------------------------------
if (Test-Path $Clone) { Remove-Item $Clone -Recurse -Force }
$t0 = [Diagnostics.Stopwatch]::StartNew()
git clone --no-hardlinks -b $Branch $Repo $Clone 2>&1 | ForEach-Object { "$_" }
$cloneExit = $LASTEXITCODE
$t0.Stop()
Mark ("RUN{0} CLONE exit={1} ms={2}" -f $RunId, $cloneExit, $t0.ElapsedMilliseconds)
Record ("CLONE exit={0} ms={1}" -f $cloneExit, $t0.ElapsedMilliseconds)
if ($cloneExit -ne 0) {
    Record "VERDICT FAIL (clone failed)"
    Mark ("RUN{0} VERDICT FAIL (clone)" -f $RunId)
    exit 2
}

Push-Location $Clone
try {
    # prove the clone carries committed content only (expected: empty)
    $dirty = (git status --porcelain | Out-String).Trim()
    Record ("CLONE_TREE_DIRTY=[{0}]" -f $dirty)
    $head = (git rev-parse HEAD | Out-String).Trim()
    Record ("CLONE_HEAD={0}" -f $head)
    Mark ("RUN{0} HEAD={1}" -f $RunId, $head)

    # ---- 2. SETUP -------------------------------------------------------------
    $t1 = [Diagnostics.Stopwatch]::StartNew()
    $setupOut = (& powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 2>&1 | Out-String)
    $setupExit = $LASTEXITCODE
    $t1.Stop()
    Add-Content -Path $Transcript -Value $setupOut
    Write-Host $setupOut
    Mark ("RUN{0} SETUP exit={1} ms={2}" -f $RunId, $setupExit, $t1.ElapsedMilliseconds)
    Record ("SETUP exit={0} ms={1}" -f $setupExit, $t1.ElapsedMilliseconds)

    # download evidence: URL, size, SHA-256 for every archive setup fetched
    foreach ($f in @('tools\ngspice-47_dll_64.7z', 'tools\ngspice-47_64.7z',
                     'tools\ngspice-44.tar.bz2')) {
        $p = Join-Path $Clone $f
        if (Test-Path $p) {
            $item = Get-Item $p
            $hash = (Get-FileHash $p -Algorithm SHA256).Hash.ToLower()
            Record ("DOWNLOAD file={0} bytes={1} sha256={2}" -f $f, $item.Length, $hash)
            Mark ("RUN{0} DOWNLOAD {1} bytes={2} sha256={3}" -f $RunId, $f, $item.Length, $hash)
        } else {
            Record ("DOWNLOAD MISSING {0}" -f $f)
        }
    }

    # pypi: URL + size + SHA-256 for every artifact pip resolves, because
    # owner decision 5 requires each download to be logged that way
    # (pypi.org for the pinned requirements is an approved host).
    New-Item -ItemType Directory -Force -Path (Join-Path $Clone 'logs') | Out-Null
    $venvPy = Join-Path $Clone '.venv\Scripts\python.exe'
    $report = Join-Path $Clone 'logs\r1-pip-report.json'
    & $venvPy -m pip install -r requirements.txt --dry-run --report $report 2>&1 |
        ForEach-Object { "$_" }
    $pipSum = Join-Path (Join-Path $Repo 'logs\cmd') 'r1_pip_sum.py'
    if ((Test-Path $report) -and (Test-Path $pipSum)) {
        $pypiOut = (& $venvPy $pipSum $report 2>&1 | Out-String)
        Add-Content -Path $Transcript -Value $pypiOut
        Write-Host $pypiOut
    } else {
        Record 'PIP-REPORT MISSING (pip --report or summariser absent)'
    }

    # ---- 3. GATE --------------------------------------------------------------
    $t2 = [Diagnostics.Stopwatch]::StartNew()
    $gateOut = (& .\.venv\Scripts\python.exe tools\run_tests.py 2>&1 | Out-String)
    $gateExit = $LASTEXITCODE
    $t2.Stop()
    Add-Content -Path $Transcript -Value $gateOut
    Write-Host $gateOut
    Mark ("RUN{0} GATE exit={1} ms={2}" -f $RunId, $gateExit, $t2.ElapsedMilliseconds)
    Record ("GATE exit={0} ms={1}" -f $gateExit, $t2.ElapsedMilliseconds)
    foreach ($pat in @('(\d+ passed[^\r\n]*)', '(\d+ failed[^\r\n]*)',
                       '(\d+ skipped[^\r\n]*)', '(\d+ error[^\r\n]*)')) {
        if ($gateOut -match $pat) { Record ("GATE-SUMMARY {0}" -f $Matches[1]) }
    }

    # ---- 4. VERIFY ------------------------------------------------------------
    $t3 = [Diagnostics.Stopwatch]::StartNew()
    $selfcheck = Join-Path $Clone 'run_selfcheck.bat'
    Record ("VERIFY-EXISTS={0}" -f (Test-Path $selfcheck))
    # Invoke by absolute path: `cmd /c run_selfcheck.bat` depends on cmd's
    # own working directory, which is what failed in R1 run 1.
    $verOut = (& $selfcheck 2>&1 | Out-String)
    $verExit = $LASTEXITCODE
    $t3.Stop()
    Add-Content -Path $Transcript -Value $verOut
    Write-Host $verOut
    Mark ("RUN{0} VERIFY exit={1} ms={2}" -f $RunId, $verExit, $t3.ElapsedMilliseconds)
    Record ("VERIFY exit={0} ms={1}" -f $verExit, $t3.ElapsedMilliseconds)
    foreach ($pat in @('SELF-CHECK: [A-Z]+', '(\d+ of \d+)')) {
        if ($verOut -match $pat) { Record ("VERIFY-DETAIL {0}" -f $Matches[1]) }
    }

    # ---- 5. VERDICT -----------------------------------------------------------
    $ok = ($cloneExit -eq 0) -and ($setupExit -eq 0) -and ($gateExit -eq 0) -and ($verExit -eq 0)
    $verdict = if ($ok) { 'PASS' } else { 'FAIL' }
    Record ("VERDICT {0} (clone={1} setup={2} gate={3} verify={4})" -f $verdict, $cloneExit, $setupExit, $gateExit, $verExit)
    Mark ("RUN{0} VERDICT {1} (clone={2} setup={3} gate={4} verify={5})" -f $RunId, $verdict, $cloneExit, $setupExit, $gateExit, $verExit)
}
finally {
    Pop-Location
    if (-not $KeepClone) {
        Remove-Item $Clone -Recurse -Force -ErrorAction SilentlyContinue
        Mark ("RUN{0} clone removed" -f $RunId)
    }
}
exit $(if ($ok) { 0 } else { 1 })
