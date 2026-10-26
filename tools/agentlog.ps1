param(
  [Parameter(Mandatory=$true)][string]$Job,
  [string]$Command = "",
  [string]$ScriptFile = "",
  [string]$Note = ""
)
$ErrorActionPreference = 'Continue'
$root   = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
$outDir = Join-Path $logDir 'out'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$jsonl  = Join-Path $logDir 'activity.jsonl'
$utf8   = New-Object System.Text.UTF8Encoding($false)
function Get-Sha([string]$s) {
  $h = [System.Security.Cryptography.SHA256]::Create().ComputeHash($utf8.GetBytes($s))
  -join ($h | ForEach-Object { $_.ToString('x2') })
}
$prev = ('0' * 64); $seq = 1
if (Test-Path $jsonl) {
  $lines = [System.IO.File]::ReadAllLines($jsonl, $utf8)
  if ($lines.Count -gt 0) { $prev = Get-Sha $lines[-1]; $seq = $lines.Count + 1 }
}
$start = Get-Date
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location $root
if ($ScriptFile) {
  $out = (& powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptFile 2>&1 | Out-String); $what = "FILE:$ScriptFile"
} elseif ($Command) {
  $out = (& powershell -NoProfile -ExecutionPolicy Bypass -Command $Command 2>&1 | Out-String); $what = $Command
} else { $out = ''; $what = '(note only)' }
$code = $LASTEXITCODE
Pop-Location
$sw.Stop()
if ($null -eq $code) { $code = 0 }
$outFile = Join-Path $outDir ('{0:D5}.txt' -f $seq)
[System.IO.File]::WriteAllText($outFile, $out, $utf8)
$tail = (($out -split "`r?`n") | Select-Object -Last 15) -join "`n"
$entry = [ordered]@{
  seq = $seq; utc = $start.ToUniversalTime().ToString('o'); job = $Job; note = $Note
  cwd = $root; command = $what; exit = $code; ms = $sw.ElapsedMilliseconds
  out_file = ("logs/out/{0:D5}.txt" -f $seq); out_sha256 = (Get-Sha $out); tail = $tail; prev = $prev
}
[System.IO.File]::AppendAllText($jsonl, ($entry | ConvertTo-Json -Compress) + "`n", $utf8)
Write-Output $out
exit $code