param(
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runtimeDir = Join-Path $repoRoot ".runtime"
$watchdogStateFile = Join-Path $runtimeDir "prod_watchdog_state.json"
$canonicalStateFile = Join-Path $runtimeDir "canonical_runtime_state.json"

function Write-RuntimeDiagnostic {
  param([string]$Event, [hashtable]$Data)
  $diagFile = Join-Path $runtimeDir "runtime_diagnostics.jsonl"
  $payload = [ordered]@{
    ts = (Get-Date).ToUniversalTime().ToString("o")
    event = $Event
  }
  foreach ($key in $Data.Keys) {
    $payload[$key] = $Data[$key]
  }
  $payload | ConvertTo-Json -Compress | Add-Content -Path $diagFile -Encoding UTF8
}

function Test-PidAliveByTasklist {
  param([int]$ProcessId)
  if (-not $ProcessId -or $ProcessId -le 0) { return $false }
  try {
    $out = (tasklist /FI "PID eq $ProcessId" /FO CSV /NH 2>$null | Out-String).Trim()
    if (-not $out) { return $false }
    if ($out.ToLower().StartsWith("info:")) { return $false }
    return $out.Contains('"' + $ProcessId + '"')
  } catch {
    return $false
  }
}

function Stop-IfRunning {
  param([int]$ProcessId, [string]$Label)
  if (-not (Test-PidAliveByTasklist -ProcessId $ProcessId)) {
    return
  }
  try {
    Write-Host "[Amicor Prod] Stopping $Label PID $ProcessId"
    Write-RuntimeDiagnostic -Event "process.stop" -Data @{ role = $Label; pid = $ProcessId; port = $Port }
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
  } catch {
    Write-Host "[Amicor Prod] Unable to stop $Label PID ${ProcessId}: $($_.Exception.Message)"
  }
}

function Get-ListenerPids {
  param([int]$TargetPort)
  $owners = @()
  $lines = netstat -ano | Select-String "LISTENING" | Select-String ":$TargetPort"
  foreach ($line in $lines) {
    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
    if ($parts.Count -lt 5) { continue }
    $pidValue = $parts[-1]
    if ($pidValue -as [int]) {
      $owners += [int]$pidValue
    }
  }
  return @($owners | Select-Object -Unique)
}

if (Test-Path $canonicalStateFile) {
  try {
    $state = Get-Content $canonicalStateFile -Raw | ConvertFrom-Json
    $statePort = if ($state.port) { [int]$state.port } else { 0 }
    if ($statePort -eq $Port) {
      if ($state.uvicorn_pid) {
        Stop-IfRunning -ProcessId ([int]$state.uvicorn_pid) -Label "uvicorn"
      }
      if ($state.launcher_pid) {
        Stop-IfRunning -ProcessId ([int]$state.launcher_pid) -Label "runtime-launcher"
      }
    }
  } catch {}
}

if (Test-Path $watchdogStateFile) {
  try {
    $watch = Get-Content $watchdogStateFile -Raw | ConvertFrom-Json
    if ($watch.watchdog_pid) {
      Stop-IfRunning -ProcessId ([int]$watch.watchdog_pid) -Label "watchdog"
    }
  } catch {}
}

$listenerPids = Get-ListenerPids -TargetPort $Port
foreach ($listenerPid in $listenerPids) {
  Stop-IfRunning -ProcessId $listenerPid -Label "listener"
}

if (Test-Path $watchdogStateFile) {
  Remove-Item $watchdogStateFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $canonicalStateFile) {
  try {
    $state = Get-Content $canonicalStateFile -Raw | ConvertFrom-Json
    $statePort = if ($state.port) { [int]$state.port } else { 0 }
    if ($statePort -eq $Port) {
      Remove-Item $canonicalStateFile -Force -ErrorAction SilentlyContinue
    }
  } catch {}
}

Write-Host "[Amicor Prod] Runtime stopped on port $Port."
exit 0
