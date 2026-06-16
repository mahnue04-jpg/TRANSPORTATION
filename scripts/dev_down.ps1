param(
  [string]$BindAddress = "127.0.0.1",
  [int]$Port = 8011
)

$ErrorActionPreference = "Stop"
$shutdownWatch = [System.Diagnostics.Stopwatch]::StartNew()

function Get-HealthStatus {
  param([string]$Url)
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 2 -UseBasicParsing
    return [int]$response.StatusCode
  } catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return -1
  }
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

function Get-VerifiedPortOwners {
  param([int]$Port)
  try {
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
      Where-Object { $_.State -in @("Listen", "Bound") }
  } catch {
    $connections = @()
  }

  $candidatePids = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
  $verified = @()
  foreach ($procId in $candidatePids) {
    if (-not $procId -or $procId -le 0) { continue }
    if (Test-PidAliveByTasklist -ProcessId $procId) {
      $verified += $procId
    }
  }
  return @($verified | Select-Object -Unique)
}

function Wait-ForListenerClear {
  param(
    [int]$Port,
    [int]$TimeoutSeconds = 20,
    [int]$RequiredConsecutive = 3
  )
  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $streak = 0
  $lastOwners = @()

  while ((Get-Date) -lt $deadline) {
    $owners = Get-VerifiedPortOwners -Port $Port
    $lastOwners = $owners
    if ($owners.Count -eq 0) {
      $streak += 1
      if ($streak -ge $RequiredConsecutive) {
        return [PSCustomObject]@{ Cleared = $true; ElapsedMs = $watch.ElapsedMilliseconds; LastOwners = @() }
      }
    } else {
      $streak = 0
    }
    Start-Sleep -Milliseconds 250
  }

  return [PSCustomObject]@{ Cleared = $false; ElapsedMs = $watch.ElapsedMilliseconds; LastOwners = $lastOwners }
}

function Write-RuntimeDiagnostic {
  param([string]$Event,[hashtable]$Data)
  $repoRoot = Split-Path -Parent $PSScriptRoot
  $diagDir = Join-Path $repoRoot ".runtime"
  $diagFile = Join-Path $diagDir "runtime_diagnostics.jsonl"
  if (-not (Test-Path $diagDir)) {
    New-Item -ItemType Directory -Path $diagDir | Out-Null
  }
  $payload = [ordered]@{
    ts = (Get-Date).ToUniversalTime().ToString("o")
    event = $Event
  }
  foreach ($key in $Data.Keys) {
    $payload[$key] = $Data[$key]
  }
  $payload | ConvertTo-Json -Compress | Add-Content -Path $diagFile -Encoding UTF8
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$stateFile = Join-Path $repoRoot ".runtime\canonical_runtime_state.json"
$apiHealthUrl = "http://$BindAddress`:$Port/api/health"

$launcherPid = $null
$uvicornPid = $null

if (Test-Path $stateFile) {
  try {
    $state = Get-Content $stateFile -Raw | ConvertFrom-Json
    if ($state.PSObject.Properties.Name -contains "launcher_pid") { $launcherPid = [int]$state.launcher_pid }
    if ($state.PSObject.Properties.Name -contains "uvicorn_pid" -and $state.uvicorn_pid) { $uvicornPid = [int]$state.uvicorn_pid }
  } catch {
    $launcherPid = $null
  }
}

if ($launcherPid) {
  try {
    $null = Get-Process -Id $launcherPid -ErrorAction Stop
    Write-Host "[Amicor Dev] Stopping launcher PID $launcherPid"
    Stop-Process -Id $launcherPid -Force -ErrorAction Stop
  } catch {
    Write-Host "[Amicor Dev] Launcher PID $launcherPid not running."
  }
}

$down = $false
for ($i = 0; $i -lt 40; $i++) {
  $status = Get-HealthStatus -Url $apiHealthUrl
  if ($status -ne 200) {
    $down = $true
    break
  }
  Start-Sleep -Milliseconds 250
}

if (-not $down -and $uvicornPid) {
  try {
    Write-Host "[Amicor Dev] Stopping uvicorn PID $uvicornPid"
    Stop-Process -Id $uvicornPid -Force -ErrorAction Stop
  } catch {}
}

$listenerPids = Get-VerifiedPortOwners -Port $Port

foreach ($listenPid in $listenerPids) {
  if (-not $listenPid) { continue }
  if ($launcherPid -and $listenPid -eq $launcherPid) { continue }
  try {
    Write-Host "[Amicor Dev] Stopping listener PID $listenPid on port $Port"
    Stop-Process -Id $listenPid -ErrorAction Stop
    $down = $true
  } catch {}
}

if (Test-Path $stateFile) {
  Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
}

$clearResult = Wait-ForListenerClear -Port $Port -TimeoutSeconds 20 -RequiredConsecutive 3
if (-not $clearResult.Cleared) {
  $owners = if ($clearResult.LastOwners) { ($clearResult.LastOwners -join ",") } else { "none" }
  Write-Host "[Amicor Dev] Listener cleanup incomplete on $Port (owners=$owners)."
  Write-RuntimeDiagnostic -Event "shutdown.listener_cleanup_timeout" -Data @{
    port = $Port
    elapsed_ms = $clearResult.ElapsedMs
    owners = $owners
    shutdown_ms = $shutdownWatch.ElapsedMilliseconds
  }
  exit 1
}

$finalStatus = Get-HealthStatus -Url $apiHealthUrl
if ($finalStatus -eq 200) {
  Write-Host "[Amicor Dev] Runtime still responding on $Port. Manual investigation required."
  Write-RuntimeDiagnostic -Event "shutdown.failed" -Data @{
    port = $Port
    final_status = $finalStatus
    shutdown_ms = $shutdownWatch.ElapsedMilliseconds
  }
  exit 1
}

Write-RuntimeDiagnostic -Event "shutdown.success" -Data @{
  port = $Port
  listener_clear_ms = $clearResult.ElapsedMs
  shutdown_ms = $shutdownWatch.ElapsedMilliseconds
}
Write-Host "[Amicor Dev] Shutdown timing: total_ms=$($shutdownWatch.ElapsedMilliseconds) listener_clear_ms=$($clearResult.ElapsedMs)"
Write-Host "[Amicor Dev] Canonical runtime stopped on port $Port."
exit 0
