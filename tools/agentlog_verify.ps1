$root  = Split-Path -Parent $PSScriptRoot
$jsonl = Join-Path $root 'logs\activity.jsonl'
$utf8  = New-Object System.Text.UTF8Encoding($false)
function Get-Sha([string]$s) {
  $h = [System.Security.Cryptography.SHA256]::Create().ComputeHash($utf8.GetBytes($s))
  -join ($h | ForEach-Object { $_.ToString('x2') })
}
$lines = [System.IO.File]::ReadAllLines($jsonl, $utf8)
$prev = ('0' * 64); $bad = 0; $i = 0
foreach ($l in $lines) {
  $i++; $e = $l | ConvertFrom-Json
  if ($e.prev -ne $prev) { "CHAIN BREAK at entry $i"; $bad++ }
  $f = Join-Path $root ($e.out_file -replace '/', '\')
  if (-not (Test-Path $f)) { "MISSING OUTPUT FILE $($e.out_file)"; $bad++ }
  elseif ((Get-Sha ([System.IO.File]::ReadAllText($f, $utf8))) -ne $e.out_sha256) { "OUTPUT HASH MISMATCH $($e.out_file)"; $bad++ }
  $prev = Get-Sha $l
}
"entries: $i  problems: $bad  head: $prev"
$lines | ForEach-Object { $_ | ConvertFrom-Json } | Group-Object job | ForEach-Object {
  "{0}: {1} entries, {2} non-zero exit" -f $_.Name, $_.Count, (($_.Group | Where-Object { $_.exit -ne 0 }).Count)
}