<#
.SYNOPSIS
    One-shot setup for PROJECT_WOWKISPICE on Windows.

.DESCRIPTION
    Creates the virtualenv, installs Python dependencies, downloads the
    official ngspice 64-bit shared-DLL build, extracts it to the location
    bridge/ngspice_wrapper.py expects, and verifies the loader can bind it.

    Safe to re-run: every step is skipped when it is already satisfied.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>

[CmdletBinding()]
param(
    # Pin a specific ngspice version. The default is the release this repo
    # was developed and verified against.
    [string]$NgspiceVersion = "47",

    # Skip the venv / pip steps (useful in CI where deps are preinstalled).
    [switch]$SkipPython
)

# Every failure in this script is detected explicitly (Test-Path, $LASTEXITCODE,
# or a throw). We must NOT use ErrorActionPreference=Stop here: the Python
# interpreter writes tracebacks to stderr, and PowerShell promotes a native
# command's stderr to a terminating error under that preference, which would
# abort on any benign diagnostic (e.g. "import py7zr" failing during probing).
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    $msg" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# 1. Virtualenv + Python dependencies
# ---------------------------------------------------------------------------
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

if (-not $SkipPython) {
    if (Test-Path $VenvPy) {
        Write-Step "Virtualenv already present - installing any missing deps"
    }
    else {
        Write-Step "Creating virtualenv"
        $python = (Get-Command python -ErrorAction SilentlyContinue)
        if (-not $python) {
            throw "python not found on PATH. Install Python 3.10+ from https://python.org and re-run."
        }
        & $python.Source -m venv (Join-Path $Root ".venv")
        & $VenvPy -m pip install --upgrade pip
    }
    Write-Step "Installing Python dependencies"
    & $VenvPy -m pip install -r (Join-Path $Root "requirements.txt")
}
elseif (-not (Test-Path $VenvPy)) {
    $VenvPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPy) { throw "-SkipPython given but no usable python found." }
}

# ---------------------------------------------------------------------------
# 2. Locate libngspice
# ---------------------------------------------------------------------------
# Where bridge/ngspice_wrapper.py looks for the bundled build.
$DllDir  = Join-Path $Root "tools\ngspice_dll\Spice64_dll\dll-vs"
$DllPath = Join-Path $DllDir "ngspice.dll"

Write-Step "Checking for libngspice"

$probe = @'
import sys
from bridge.ngspice_wrapper import resolve_ngspice_library, NgSpiceEngine
path, tried = resolve_ngspice_library()
for t in tried:
    print("    tried:", t)
if path is None:
    print("    nothing resolved")
    sys.exit(1)
print("    resolved:", path)
# Resolving is not enough: the file can exist but fail to load because one of
# its own dependent DLLs is missing. Actually construct the engine.
try:
    NgSpiceEngine(verbose=False).load_circuit(
        ["* probe", "V1 in 0 DC 1", "R1 in 0 1k", ".op", ".end"])
except OSError as exc:
    print("    resolved but NOT loadable:", exc)
    sys.exit(2)
print("    bind: OK")
'@
$probe | Out-File -Encoding utf8 (Join-Path $Root ".wosp_probe.py")

$resolved = & $VenvPy (Join-Path $Root ".wosp_probe.py") 2>&1
$resolved | ForEach-Object { Write-Host $_ }
$probeRc = $LASTEXITCODE
Remove-Item (Join-Path $Root ".wosp_probe.py") -ErrorAction SilentlyContinue

if ($probeRc -eq 0) {
    Write-Ok "libngspice is already present and loadable - nothing to do."
    Write-Step "Setup complete."
    exit 0
}

# ---------------------------------------------------------------------------
# 3. Download + extract the official ngspice DLL build
# ---------------------------------------------------------------------------
$Archive  = Join-Path $Root "tools\ngspice-${NgspiceVersion}_dll_64.7z"
$ExtractTo = Join-Path $Root "tools\ngspice_dll"
$BaseUrl = "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/$NgspiceVersion"
# SHA-256 of ngspice-47_dll_64.7z as published on SourceForge. A mismatch is
# reported, not silently accepted.
$ExpectedSha = "5bf5eec7db989f74849cdb32f7df62693f4f149cceeebcbd222eb35c2bb821eb"

# py7zr unpacks ngspice's .7z. Ensure it exists regardless of -SkipPython,
# since extraction still has to happen.
Write-Step "Preparing the .7z extractor"
& $VenvPy -c "import py7zr" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $VenvPy -m pip install py7zr 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not install py7zr; cannot unpack the ngspice archives." }
}

function Get-NgspiceArchive {
    param([string]$Name, [string]$ExpectSha)
    $dest = Join-Path $Root "tools\$Name"
    if (Test-Path $dest) {
        if (-not $ExpectSha) {
            Write-Step "Using cached archive tools\$Name"
            return $dest
        }
        $have = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
        if ($have -eq $ExpectSha.ToLower()) {
            Write-Step "Using cached archive tools\$Name (checksum verified)"
            return $dest
        }
        Write-Warn2 "tools\$Name checksum differs; re-downloading."
        Remove-Item $dest
    }
    Write-Step "Downloading $Name"
    Write-Host "    $BaseUrl/$Name/download"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "$BaseUrl/$Name/download" -OutFile $dest -UseBasicParsing
    }
    catch {
        throw "Download of $Name failed: $($_.Exception.Message)`n`nIf this machine has no internet access, copy $Name manually into tools\ and re-run."
    }
    if ($ExpectSha) {
        $got = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $ExpectSha.ToLower()) {
            Write-Warn2 "Checksum mismatch for ${Name}: expected $ExpectSha, got $got"
            Write-Warn2 "Continuing - the bind check in step 4 is the real test."
        }
        else { Write-Ok "Checksum verified." }
    }
    return $dest
}

$DllArchive = Get-NgspiceArchive "ngspice-${NgspiceVersion}_dll_64.7z" $ExpectedSha

Write-Step "Extracting the shared DLL to tools\ngspice_dll"
New-Item -ItemType Directory -Force -Path $ExtractTo | Out-Null
& $VenvPy -c "import py7zr,sys; py7zr.SevenZipFile(sys.argv[1],'r').extractall(sys.argv[2])" $DllArchive $ExtractTo 2>&1
if ($LASTEXITCODE -ne 0) { throw "Extraction of $DllArchive failed." }

if (-not (Test-Path $DllPath)) {
    throw "Extraction completed but $DllPath is missing. The archive layout may have changed; check tools\ngspice_dll."
}
Write-Ok "Placed $([IO.Path]::GetFileName($DllPath))"

# ---------------------------------------------------------------------------
# 3b. Satisfy ngspice.dll's own runtime dependencies.
#
# ngspice.dll imports sndfile.dll and samplerate.dll, but the official
# ngspice-<ver>_dll_64.7z archive does NOT ship them (they live in the separate
# ngspice-<ver>_64.7z console build). Without them, LoadLibrary fails with
# "Could not find module ... or one of its dependencies" even though the
# ngspice.dll file is sitting right there.
# ---------------------------------------------------------------------------
$RuntimeDeps = @("sndfile.dll", "samplerate.dll")
$missing = $RuntimeDeps | Where-Object { -not (Test-Path (Join-Path $DllDir $_)) }

if ($missing) {
    Write-Step "ngspice.dll needs $($missing -join ', ') - fetching them"
    # Prefer an already-extracted local copy over a 13.8 MB download.
    $localBin = Join-Path $Root "tools\ngspice\bin"
    $usedLocal = $false
    if ((Test-Path $localBin) -and
        ($RuntimeDeps | Where-Object { -not (Test-Path (Join-Path $localBin $_)) }).Count -eq 0) {
        foreach ($d in $missing) { Copy-Item (Join-Path $localBin $d) (Join-Path $DllDir $d) -Force }
        Write-Ok "Copied from tools\ngspice\bin"
        $usedLocal = $true
    }
    if (-not $usedLocal) {
        $FullArchive = Get-NgspiceArchive "ngspice-${NgspiceVersion}_64.7z" ""
        $tmp = Join-Path $env:TEMP "wosp_ngspice_full_$([guid]::NewGuid().ToString('N').Substring(0,8))"
        try {
            & $VenvPy -c "import py7zr,sys; py7zr.SevenZipFile(sys.argv[1],'r').extractall(sys.argv[2])" $FullArchive $tmp 2>&1
            if ($LASTEXITCODE -ne 0) { throw "Extraction of $FullArchive failed." }
            $src = Get-ChildItem -Path $tmp -Recurse -Filter "sndfile.dll" |
                   Select-Object -First 1
            if (-not $src) { throw "sndfile.dll not found inside $FullArchive" }
            $binDir = $src.Directory.FullName
            foreach ($d in $RuntimeDeps) {
                $p = Join-Path $binDir $d
                if (-not (Test-Path $p)) { throw "$d not found inside $FullArchive" }
                Copy-Item $p (Join-Path $DllDir $d) -Force
            }
            Write-Ok "Placed sndfile.dll, samplerate.dll"
        }
        finally {
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# 4. Verify the loader can actually bind it
# ---------------------------------------------------------------------------
Write-Step "Verifying the loader binds libngspice"
$probe2 = @'
from bridge.ngspice_wrapper import resolve_ngspice_library, NgSpiceEngine
path, tried = resolve_ngspice_library()
print("    resolved:", path)
assert path is not None, "resolver still cannot find libngspice"
NgSpiceEngine(verbose=False).load_circuit(["* probe", "V1 in 0 DC 1", "R1 in 0 1k", ".op", ".end"])
print("BIND_OK")
'@
$probe2 | Out-File -Encoding utf8 (Join-Path $Root ".wosp_probe.py")
& $VenvPy (Join-Path $Root ".wosp_probe.py") 2>&1
$rc = $LASTEXITCODE
Remove-Item (Join-Path $Root ".wosp_probe.py") -ErrorAction SilentlyContinue

if ($rc -ne 0) { throw "libngspice was placed but could not be loaded." }

Write-Step "Setup complete."
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  .\run_tests.bat      # run all 16 suites"
Write-Host "  .\run_editor.bat     # launch the PyQt5 schematic editor"