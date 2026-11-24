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

<#
Resolve the full runtime dependency closure of the GUI executable. Qt5 and the
MinGW-w64 toolchain produce dynamically linked binaries: a clean Windows machine
has none of these DLLs, so every non-system dependency must be shipped. Only DLLs
found under the MSYS2 prefix (or the Qt plugin directory) are bundled; anything
else (kernel32.dll, api-ms-win-*, d3d11.dll, ...) is provided by Windows itself.
#>
function Get-RuntimeClosure {
    param(
        [Parameter(Mandatory = $true)][string[]]$Roots,
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$QtPlugins
    )
    $objdump = Join-Path $Prefix 'bin\objdump.exe'
    if (-not (Test-Path $objdump)) { throw "objdump.exe not found under $Prefix\bin" }
    $SearchDirs = @((Join-Path $Prefix 'bin'), (Join-Path $QtPlugins 'platforms'))

    $seen = @{}
    $queue = [System.Collections.Generic.Queue[string]]::new()
    foreach ($root in $Roots) { if (Test-Path $root) { $queue.Enqueue($root) } }
    while ($queue.Count -gt 0) {
        $file = $queue.Dequeue()
        $name = (Split-Path $file -Leaf).ToLowerInvariant()
        if ($seen.ContainsKey($name)) { continue }
        $seen[$name] = $file

        $deps = & $objdump -p $file 2>$null |
            Where-Object { $_ -match '^\s*DLL Name:' } |
            ForEach-Object { ($_ -split ':', 2)[1].Trim() }
        foreach ($dep in $deps) {
            $key = $dep.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $hit = $null
            foreach ($dir in $SearchDirs) {
                $candidate = Join-Path $dir $dep
                if (Test-Path $candidate) { $hit = $candidate; break }
            }
            # Not found in MSYS2 => a Windows system DLL, nothing to bundle.
            if ($hit) { $queue.Enqueue($hit) }
        }
    }
    return $seen
}

Step '1/6 Build GUI from source (cmake -Werror)'
cmake -S gui -B gui/build_release -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:\msys64\ucrt64
if ($LASTEXITCODE -ne 0) { throw 'cmake configure failed' }
cmake --build gui/build_release --config Release
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }

Step '2/6 Build CLI from source (cargo)'
cargo build --release -p wosp-cli
if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }

if (-not $SkipNgspice) {
    Step '3/6 Fetch + verify ngspice DLL (setup.ps1)'
    powershell -ExecutionPolicy Bypass -File setup.ps1
    if ($LASTEXITCODE -ne 0) { throw 'setup.ps1 failed' }
} else {
    Step '3/6 SKIPPED ngspice fetch (-SkipNgspice)'
}

Step '4/6 Resolve Qt5 + MinGW runtime dependency closure'
$Prefix = if ($env:MINGW_PREFIX) { $env:MINGW_PREFIX } else { 'C:\msys64\ucrt64' }
$Qmake = @((Join-Path $Prefix 'bin\qmake-qt5.exe'), (Join-Path $Prefix 'bin\qmake.exe')) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
$QtPlugins = if ($Qmake) { (& $Qmake -query QT_INSTALL_PLUGINS 2>$null | Select-Object -First 1) } else { $null }
if (-not $QtPlugins -or -not (Test-Path $QtPlugins)) {
    $QtPlugins = Join-Path $Prefix 'share\qt5\plugins'
}
$GuiExe = Join-Path $Root 'gui\build_release\wowkispice_gui.exe'
$QWindows = Join-Path $QtPlugins 'platforms\qwindows.dll'
$Runtime = Get-RuntimeClosure -Roots @($GuiExe, $QWindows) -Prefix $Prefix -QtPlugins $QtPlugins
Write-Host "Resolved $($Runtime.Count) runtime files (Qt5 + MinGW + transitive):"
$Runtime.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host "  $($_.Key)" }

Step '5/6 Stage installer inputs from tracked sources + built artifacts'
$Stage = Join-Path $Root 'installer\build\staging'
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'tools\ngspice_dll\Spice64_dll\dll-vs') | Out-Null

Copy-Item gui\build_release\wowkispice_gui.exe (Join-Path $Stage 'wowkispice_gui.exe')

# Bundle every Qt5 / MinGW-w64 runtime DLL next to the GUI. A clean Windows
# machine has none of these, so relying on MSYS2 being installed is not viable.
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'platforms') | Out-Null
foreach ($entry in $Runtime.GetEnumerator()) {
    $leaf = $entry.Key
    if ($leaf -eq 'wowkispice_gui.exe') { continue }
    if ($leaf -eq 'qwindows.dll') {
        Copy-Item $entry.Value (Join-Path $Stage 'platforms\qwindows.dll') -Force
    } else {
        Copy-Item $entry.Value (Join-Path $Stage $leaf) -Force
    }
}

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

Step '6/6 Compile NSIS installer'
$Makensis = 'C:\Program Files (x86)\NSIS\makensis.exe'
if (-not (Test-Path $Makensis)) { $Makensis = 'C:\Program Files\NSIS\makensis.exe' }
if (-not (Test-Path $Makensis)) { throw 'makensis.exe not found' }
& $Makensis /DSTAGING_DIR="$Stage" /DVERSION="$(Get-Content VERSION)" installer\wowkispice_installer.nsi
if ($LASTEXITCODE -ne 0) { throw 'makensis failed' }
Write-Host "`nINSTALLER BUILD OK: installer\wowkispice_installer.exe"
