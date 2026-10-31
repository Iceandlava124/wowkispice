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

# Owner decision Q5(a), two changes from the version that forked the chain:
#
#   1. THE COMMAND RUNS FIRST. seq/prev are allocated only after the command
#      has finished. The old order (allocate, then run) let two concurrent
#      jobs both read seq 253 before either had run -- entries 254/254, one
#      output file overwritten, chain break at 257.
#   2. THE ALLOCATION AND THE APPEND SHARE A MUTEX. Running first removes
#      most of the window (two jobs no longer hold a seq while working), but
#      two jobs can still finish at the same instant, so read-last /
#      allocate / write-output / append happen one at a time.
#
# The chain itself is NOT re-sealed: logs/activity.jsonl keeps its forked
# history on purpose (owner decision Q5a), and the two bad entries stay
# recorded in docs/STATE.md.

$start = Get-Date
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location $root
if ($ScriptFile) {
  $out = (& powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptFile 2>&1 | Out-String); $what = "FILE:$ScriptFile"
} elseif ($Command) {
  # Two PS 5.1 traps, both measured this session: (1) -Command collapses a
  # native exit 3 to 1, so re-exit with the exact $LASTEXITCODE inside the
  # child; (2) passing $inner as a -Command argument strips its embedded
  # double quotes (SyntaxError: invalid syntax), so hand the child the
  # script base64-encoded instead of as a quoted argument.
  $inner = "$Command; if (`$null -ne `$LASTEXITCODE) { exit `$LASTEXITCODE }"
  $b64 = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($inner))
  $out = (& powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $b64 2>&1 | Out-String); $what = $Command
} else { $out = ''; $what = '(note only)' }
$code = $LASTEXITCODE
Pop-Location
$sw.Stop()
if ($null -eq $code) { $code = 0 }

$mutex = New-Object System.Threading.Mutex($false, 'WOSP_AGENTLOG_SEQ')
$held = $false
try {
  try {
    $held = $mutex.WaitOne(120000)
  }
  catch [System.Threading.AbandonedMutexException] {
    # The previous holder died holding it; we own it now.
    $held = $true
  }
  if (-not $held) {
    throw "agentlog: the seq mutex was held for over 120 s - refusing to append, because guessing a seq would fork the chain"
  }

  $prev = ('0' * 64); $seq = 1
  if (Test-Path $jsonl) {
    $lines = [System.IO.File]::ReadAllLines($jsonl, $utf8)
    if ($lines.Count -gt 0) {
      $prev = Get-Sha $lines[-1]
      # max+1 rather than count+1: the log already contains a duplicated seq
      # (254), so count+1 can hand out a number that is already taken.
      $max = 0
      foreach ($l in $lines) {
        $n = [regex]::Match($l, '"seq":(\d+)').Groups[1].Value
        if ($n -and [int]$n -gt $max) { $max = [int]$n }
      }
      $seq = $max + 1
    }
  }

  $outFile = Join-Path $outDir ('{0:D5}.txt' -f $seq)
  [System.IO.File]::WriteAllText($outFile, $out, $utf8)
  $tail = (($out -split "`r?`n") | Select-Object -Last 15) -join "`n"
  $entry = [ordered]@{
    seq = $seq; utc = $start.ToUniversalTime().ToString('o'); job = $Job; note = $Note
    cwd = $root; command = $what; exit = $code; ms = $sw.ElapsedMilliseconds
    out_file = ("logs/out/{0:D5}.txt" -f $seq); out_sha256 = (Get-Sha $out); tail = $tail; prev = $prev
  }
  [System.IO.File]::AppendAllText($jsonl, ($entry | ConvertTo-Json -Compress) + "`n", $utf8)
}
finally {
  if ($held) { try { $mutex.ReleaseMutex() } catch { } }
  $mutex.Dispose()
}

Write-Output $out
exit $code
