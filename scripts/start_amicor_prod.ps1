param(
  [string]$BindAddress = "0.0.0.0",
  [int]$Port = 8000,
  [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runtimeDir = Join-Path $repoRoot ".runtime"
if (-not (Test-Path $runtimeDir)) {
  New-Item -Path $runtimeDir -ItemType Directory | Out-Null
}

$watchdogStateFile = Join-Path $runtimeDir "prod_watchdog_state.json"
$canonicalStateFile = Join-Path $runtimeDir "canonical_runtime_state.json"

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

function Get-HealthyStatus {
  param([string]$Url)
  try {
    # UseBasicParsing avoids interactive script-execution prompts in legacy PowerShell hosts.
    $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
    return [int]$resp.StatusCode
  } catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return -1
  }
}

if (Test-Path $watchdogStateFile) {
  try {
    $state = Get-Content $watchdogStateFile -Raw | ConvertFrom-Json
    $statePort = if ($state.port) { [int]$state.port } else { 0 }
    $pid = [int]$state.watchdog_pid
    if ($statePort -eq $Port -and (Test-PidAliveByTasklist -ProcessId $pid)) {
      Write-Host "[Amicor Prod] Watchdog already running on port $Port (PID=$pid)."
      exit 0
    }
  } catch {}
}

$watchdogScript = Join-Path $repoRoot "scripts/amicor_runtime_watchdog.ps1"
if (-not (Test-Path $watchdogScript)) {
  throw "Missing watchdog script: $watchdogScript"
}

$args = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $watchdogScript,
  "-BindAddress", $BindAddress,
  "-Port", [string]$Port,
  "-LogLevel", $LogLevel
)

$proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -PassThru
Write-Host "[Amicor Prod] Watchdog started (PID=$($proc.Id))."

$healthUrl = "http://127.0.0.1:$Port/api/health"
$maxChecks = 45
$healthy = $false
for ($i = 0; $i -lt $maxChecks; $i++) {
  $status = Get-HealthyStatus -Url $healthUrl
  if ($status -eq 200) {
    $healthy = $true
    break
  }
  Start-Sleep -Seconds 1
}

if (-not $healthy) {
  Write-Host "[Amicor Prod] Runtime did not become healthy at $healthUrl within timeout."
  exit 1
}

if (Test-Path $canonicalStateFile) {
  try {
    $canonical = Get-Content $canonicalStateFile -Raw | ConvertFrom-Json
    $uvicornPid = $canonical.uvicorn_pid
    Write-Host "[Amicor Prod] Runtime healthy (uvicorn PID=$uvicornPid)."
  } catch {
    Write-Host "[Amicor Prod] Runtime healthy."
  }
} else {
  Write-Host "[Amicor Prod] Runtime healthy."
}

Write-Host "[Amicor Prod] App: http://127.0.0.1:$Port/app"
Write-Host "[Amicor Prod] API Health: $healthUrl"
exit 0
