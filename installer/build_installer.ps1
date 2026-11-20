<#
.SYNOPSIS
Builds a reproducible WOWKISPICE installer from TRACKED SOURCES ONLY.

.DESCRIPTION
Layer 4: the old installer .nsi referenced gitignored binaries (gui/build exe,
*.dll) and had fatal NSIS syntax errors. This script:
  1. builds the GUI from source (cmake, -Werror)
  2. builds the CLI from source (cargo)
  3. runs setup.ps1 to fetch/extract the official ngspice DLL (SHA-verified)
  4. stages every input into installer/build/staging/
  5. compiles installer/wowkispice_installer.nsi with makensis
No gitignored binary is assumed to pre-exist -- everything is produced or
fetched here, so a fresh clone can reproduce the installer.

.PARAMETER SkipNgspice
Skip ngspice fetch (for offline smoke tests of the packaging steps only).
#>
param([switch]$SkipNgspice)

$ErrorActionPreference = 'Stop'
$InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $InstallerDir
Set-Location $Root

function Step($msg) { Write-Host "`n=== $msg ===" }

Step '1/5 Build GUI from source (cmake -Werror)'
cmake -S gui -B gui/build_release -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:\msys64\ucrt64
if ($LASTEXITCODE -ne 0) { throw 'cmake configure failed' }
cmake --build gui/build_release --config Release
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }

Step '2/5 Build CLI from source (cargo)'
cargo build --release -p wosp-cli
if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }

if (-not $SkipNgspice) {
    Step '3/5 Fetch + verify ngspice DLL (setup.ps1)'
    powershell -ExecutionPolicy Bypass -File setup.ps1
    if ($LASTEXITCODE -ne 0) { throw 'setup.ps1 failed' }
} else {
    Step '3/5 SKIPPED ngspice fetch (-SkipNgspice)'
}

Step '4/5 Stage installer inputs from tracked sources + built artifacts'
$Stage = Join-Path $Root 'installer\build\staging'
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'tools\ngspice_dll\Spice64_dll\dll-vs') | Out-Null

Copy-Item gui\build_release\wowkispice_gui.exe (Join-Path $Stage 'wowkispice_gui.exe')
Copy-Item target\x86_64-pc-windows-gnu\release\wosp-cli.exe (Join-Path $Stage 'wosp-cli.exe') -ErrorAction SilentlyContinue
Copy-Item installer\tools\run_selfcheck.bat (Join-Path $Stage 'run_selfcheck.bat')
Copy-Item firmware\esp32_buck_controller\src\firmware_control.dll (Join-Path $Stage 'firmware_control.dll') -ErrorAction SilentlyContinue
if (Test-Path tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll) {
    Copy-Item tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll (Join-Path $Stage 'tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll')
} elseif (-not $SkipNgspice) {
    throw 'ngspice.dll missing after setup.ps1 - cannot package'
}
Write-Host "Staged files:"
Get-ChildItem -Recurse -File $Stage | % { "  $($_.FullName.Replace($Stage,''))  $($_.Length) bytes" }

Step '5/5 Compile NSIS installer'
$Makensis = 'C:\Program Files (x86)\NSIS\makensis.exe'
if (-not (Test-Path $Makensis)) { $Makensis = 'C:\Program Files\NSIS\makensis.exe' }
if (-not (Test-Path $Makensis)) { throw 'makensis.exe not found' }
& $Makensis /DSTAGING_DIR="$Stage" /DVERSION="$(Get-Content VERSION)" installer\wowkispice_installer.nsi
if ($LASTEXITCODE -ne 0) { throw 'makensis failed' }
Write-Host "`nINSTALLER BUILD OK: installer\wowkispice_installer.exe"
