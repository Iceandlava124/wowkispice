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
        # Pick a WINDOWS-native interpreter. The first `python` on PATH may be
        # MSYS2/Cygwin (sys.platform 'msys'/'cygwin'), and `venv` from such an
        # interpreter creates a POSIX-layout env (bin/ instead of Scripts/),
        # which every Windows entry point then fails to find. Prefer the
        # verified 3.12 via the py launcher, then any py-launcher Python,
        # then a Windows-native `python`.
        function Select-WindowsPython {
            $candidates = @()
            $launcher = Get-Command py -ErrorAction SilentlyContinue
            if ($launcher) {
                $candidates += @{ Exe = $launcher.Source; Args = @("-3.12") }
                $candidates += @{ Exe = $launcher.Source; Args = @("-3") }
            }
            $python = Get-Command python -ErrorAction SilentlyContinue
            if ($python) { $candidates += @{ Exe = $python.Source; Args = @() } }
            foreach ($c in $candidates) {
                # NOTE: native stdout arrives as an ARRAY of lines; stringifying
                # it ("$out") joins with spaces and collapses the two lines into
                # one, which silently rejected every candidate. Keep the array.
                try {
                    $out = @(& $c["Exe"] @($c["Args"]) -c "import sys, sysconfig; print(sys.platform); print('%d.%d.%d' % sys.version_info[:3]); print(sysconfig.get_platform())" 2>$null)
                }
                catch { continue }
                $lines = @($out | ForEach-Object { "$_" } | Where-Object { $_.Trim() -ne "" })
                if ($lines.Count -lt 3) { continue }
                if ($lines[0].Trim() -ne "win32") { continue }  # rejects MSYS/Cygwin python
                # MSYS2 ucrt64 python ALSO reports sys.platform 'win32' but
                # builds a bin/-layout venv instead of Scripts\, which every
                # Windows entry point then fails to find. Its distutils
                # platform is 'mingw_*'; a real CPython says 'win-*'.
                if ($lines[2].Trim() -notlike "win-*") { continue }
                $verText = $lines[1].Trim()
                $parts = $verText.Split(".")
                if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
                    continue  # selfcheck needs Python >= 3.10; verified target is 3.12
                }
                Write-Ok "interpreter: $verText at $($c['Exe']) $($c['Args'] -join ' ')"
                return $c
            }
            return $null
        }
        $selected = Select-WindowsPython
        if (-not $selected) {
            throw "No Windows-native Python 3.10+ found (checked py launcher -3.12, -3, and python on PATH). An MSYS2/Cygwin python cannot create a Windows venv. Install Python 3.12 from https://python.org and re-run."
        }
        & $selected["Exe"] @($selected["Args"] + @("-m", "venv", (Join-Path $Root ".venv")))
        if (-not (Test-Path $VenvPy)) {
            throw "venv creation failed: $VenvPy was not produced. The interpreter ($($selected['Exe'])) may have failed; run it manually with '-m venv .venv' to see why."
        }
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

# A probe that never runs must never read as success: if the venv is absent
# (or the interpreter crashed), $LASTEXITCODE is stale from whatever ran
# before, and a stale 0 used to report "libngspice is already present" on a
# machine that had just failed to create its venv. Fail loudly instead.
if (-not (Test-Path $VenvPy)) {
    throw "No venv interpreter at $VenvPy - the setup cannot probe libngspice. Re-run after fixing the Python step above."
}
$global:LASTEXITCODE = 1  # default to failure; the probe overwrites it

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
# SHA-256 of ngspice-47_dll_64.7z as published on SourceForge. A mismatch
# aborts setup (Test-NgspiceArchive below) instead of warning and continuing.
$ExpectedSha = "5bf5eec7db989f74849cdb32f7df62693f4f149cceeebcbd222eb35c2bb821eb"

# py7zr unpacks ngspice's .7z. Ensure it exists regardless of -SkipPython,
# since extraction still has to happen.
Write-Step "Preparing the .7z extractor"
& $VenvPy -c "import py7zr" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $VenvPy -m pip install py7zr 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not install py7zr; cannot unpack the ngspice archives." }
}

# SourceForge serves an HTML download page instead of the file unless a
# non-default User-Agent is sent. Measured 2026-10-30 (log entries #278,
# #295): default UA -> HTML body in 0 of 4 fetches avoided - 4 of 4 attempts
# returned 130879/132538 bytes titled 'Download ngspice-47_dll_64.7z (ngspice)'
# with a mismatched sha256; User-Agent 'WISP-R1-probe/1.0' -> the real
# 4385088-byte archive with the pinned sha256 in 4 of 4 attempts, both with
# and without -MaximumRedirection 8. Changing this string is unmeasured.
$FetchUserAgent = 'WISP-R1-probe/1.0'

# The 7z signature, byte for byte, as measured from the real archive in log
# entry #276 (magic_hex=377abcaf271c0004 -> 37 7A BC AF 27 1C).
$SevenZipMagic = @(0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C)

function Test-NgspiceArchive {
    # Refuse anything that is not the archive we asked for, whether it came
    # from the network or from the cache. Before this existed, an HTML page
    # was saved as the .7z and only a yellow checksum warning followed, so it
    # flowed on into py7zr extraction (measured in log entry #278).
    param([string]$Path, [string]$Name, [string]$ExpectSha)
    $len = (Get-Item -LiteralPath $Path).Length
    $fs = [IO.File]::OpenRead($Path)
    try {
        $head = New-Object byte[] 6
        $read = $fs.Read($head, 0, 6)
    }
    finally { $fs.Close() }
    $is7z = ($read -eq 6)
    if ($is7z) {
        for ($i = 0; $i -lt 6; $i++) {
            if ($head[$i] -ne $SevenZipMagic[$i]) { $is7z = $false }
        }
    }
    if (-not $is7z) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        if ($read -lt 6) {
            throw "tools\$Name is only $len bytes - too small to be the archive. Re-run setup.ps1, or download $Name manually into tools\ and re-run."
        }
        $hex = ($head | ForEach-Object { $_.ToString('x2') }) -join ' '
        throw "tools\$Name is not a 7z archive (first bytes: $hex). SourceForge answered with an HTML page instead of the file, so the download was discarded. Re-run setup.ps1, or copy $Name manually into tools\ and re-run."
    }
    if ($ExpectSha) {
        $got = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $ExpectSha.ToLower()) {
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
            throw "Checksum mismatch for ${Name}: expected $ExpectSha, got $got. The file was discarded; re-run setup.ps1 to fetch it again, or copy it manually into tools\ and re-run."
        }
    }
    return $true
}

function Get-NgspiceArchive {
    param([string]$Name, [string]$ExpectSha)
    $dest = Join-Path $Root "tools\$Name"
    if (Test-Path $dest) {
        if ($ExpectSha) {
            $have = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
            if ($have -eq $ExpectSha.ToLower()) {
                Write-Step "Using cached archive tools\$Name (checksum verified)"
                return $dest
            }
            Write-Warn2 "tools\$Name checksum differs; re-downloading."
            Remove-Item $dest
        }
        else {
            # No pin for this archive (the console build), so the magic bytes
            # are the only check - and a cached HTML page from an older run
            # must not be trusted just because it has a filename.
            try {
                # `$null =` is load-bearing: without it the validator's
                # `return $true` joined Get-NgspiceArchive's own output and
                # the caller received @($true, $dest) - measured in R1 run 1,
                # where py7zr was handed the string 'True' (FileNotFoundError)
                # and setup.ps1 exited 1 on a fresh clone.
                $null = Test-NgspiceArchive -Path $dest -Name $Name -ExpectSha ''
                Write-Step "Using cached archive tools\$Name (7z header verified)"
                return $dest
            }
            catch {
                Write-Warn2 "cached tools\$Name rejected: $($_.Exception.Message)"
                # Test-NgspiceArchive already removed the bad file, so the
                # download below starts from a clean state.
            }
        }
    }
    Write-Step "Downloading $Name"
    Write-Host "    $BaseUrl/$Name/download"
    # Owner action 1: one measured retry. SourceForge answered with an HTML
    # page instead of the archive in #276/#278, and again during this
    # session's R1 clone install (first bytes 3c 68 74 6d 6c 3e - job
    # R1-RUN1F), so one attempt turned a flaky mirror into a failed install.
    # Every attempt downloads AND validates, so the retry also covers a
    # truncated or wrong payload, and the loop is bounded at three.
    $MaxAttempts = 3
    $attempt = 0
    $lastError = ''
    while ($attempt -lt $MaxAttempts) {
        $attempt++
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri "$BaseUrl/$Name/download" -OutFile $dest -UseBasicParsing -UserAgent $FetchUserAgent -MaximumRedirection 8
            $null = Test-NgspiceArchive -Path $dest -Name $Name -ExpectSha $ExpectSha
            break
        }
        catch {
            $lastError = $_.Exception.Message
            if ($attempt -ge $MaxAttempts) {
                throw "Download of $Name failed after $attempt attempts: $lastError`n`nIf this machine has no internet access, copy $Name manually into tools\ and re-run."
            }
            Write-Warn2 "attempt $attempt of ${MaxAttempts} failed ($lastError); retrying"
            Start-Sleep -Seconds 2
        }
    }
    if ($ExpectSha) { Write-Ok "Checksum verified." }
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
if (-not (Test-Path $VenvPy)) {
    throw "No venv interpreter at $VenvPy - cannot verify the libngspice bind."
}
$global:LASTEXITCODE = 1  # a verification that never runs must not read as success
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

# ---------------------------------------------------------------------------
# 5. Cleanup orphaned processes, fetch prebuilt patched QEMU, and run doctor
# ---------------------------------------------------------------------------
Write-Step "Cleaning up orphaned QEMU processes"
try {
    & $VenvPy (Join-Path $Root "tools\cleanup_qemu.py") 2>&1 | Out-Host
} catch {
    Write-Warn "Cleanup skipped: $_"
}

Write-Step "Checking for prebuilt patched QEMU"
try {
    & $VenvPy (Join-Path $Root "tools\fetch_qemu.py") 2>&1 | Out-Host
} catch {
    Write-Warn "QEMU fetch skipped: $_"
}

Write-Step "Running environment doctor"
try {
    & $VenvPy (Join-Path $Root "tools\doctor.py") 2>&1 | Out-Host
} catch {
    Write-Warn "Doctor check skipped: $_"
}

# Write .env.local if toolchain resolver can find things
try {
    & $VenvPy -c "from bridge.toolchain_resolver import ToolchainResolver; r=ToolchainResolver(); print(r.write_env_local())" 2>&1 | Out-Null
} catch {
    # ignore
}

Write-Step "Setup complete."
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  python tools\doctor.py  # check environment health"
Write-Host "  .\run_selfcheck.bat    # verify this machine end to end"
Write-Host "  .\run_tests.bat        # run the full test suite"
Write-Host "  .\run_editor.bat       # launch the PyQt5 schematic editor"