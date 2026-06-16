param(
  [string]$BindAddress = "127.0.0.1",
  [int]$Port = 8011,
  [switch]$Reload,
  [string]$LogLevel = "info",
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

$startupStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

function Test-ProcessAlive {
  param([int]$ProcessId)
  if (-not $ProcessId -or $ProcessId -le 0) { return $false }
  try {
    $null = Get-Process -Id $ProcessId -ErrorAction Stop
    return $true
  } catch {
    return $false
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

function Get-HealthStatus {
  param([string]$Url, [int]$TimeoutSec = 3)
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec $TimeoutSec -UseBasicParsing
    return [int]$response.StatusCode
  } catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return -1
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

function Wait-ForPortRelease {
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
        return [PSCustomObject]@{
          Released = $true
          ElapsedMs = $watch.ElapsedMilliseconds
          LastOwners = @()
        }
      }
    } else {
      $streak = 0
    }

    Start-Sleep -Milliseconds 250
  }

  return [PSCustomObject]@{
    Released = $false
    ElapsedMs = $watch.ElapsedMilliseconds
    LastOwners = $lastOwners
  }
}

function Get-UvicornPidFromState {
  param([string]$StateFile)
  if (-not (Test-Path $StateFile)) { return $null }
  try {
    $state = Get-Content $StateFile -Raw | ConvertFrom-Json
    if ($state.PSObject.Properties.Name -contains "uvicorn_pid" -and $state.uvicorn_pid) {
      return [int]$state.uvicorn_pid
    }
  } catch {}
  return $null
}

function Wait-ForConsecutiveReadiness {
  param(
    [string]$ApiHealthUrl,
    [string]$AppUrl,
    [string]$GovernanceUrl,
    [string]$StateFile,
    [int]$Port,
    [int]$TimeoutSeconds = 90,
    [int]$RequiredConsecutive = 2
  )

  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $okStreak = 0
  $transientFailures = 0
  $hardFailures = 0
  $uvicornPid = $null
  $uvicornSeenAtMs = $null
  $listenerAcquiredAtMs = $null
  $escalationCheckpoints = @(20, 40, 60)
  $escalationLogged = @{}
  foreach ($c in $escalationCheckpoints) { $escalationLogged[$c] = $false }
  $lastStatusLine = ""

  while ((Get-Date) -lt $deadline) {
    $apiStatus = Get-HealthStatus -Url $ApiHealthUrl -TimeoutSec 3
    $appStatus = Get-HealthStatus -Url $AppUrl -TimeoutSec 3
    $govStatus = Get-HealthStatus -Url $GovernanceUrl -TimeoutSec 3
    $lastStatusLine = "api=$apiStatus,app=$appStatus,governance=$govStatus"

    $statePid = Get-UvicornPidFromState -StateFile $StateFile
    if ($statePid -and -not $uvicornPid) { $uvicornPid = $statePid }

    if ($uvicornPid -and -not $uvicornSeenAtMs -and (Test-PidAliveByTasklist -ProcessId $uvicornPid)) {
      $uvicornSeenAtMs = $watch.ElapsedMilliseconds
    }

    if ($uvicornPid -and -not $listenerAcquiredAtMs) {
      $owners = Get-VerifiedPortOwners -Port $Port
      if ($owners -contains $uvicornPid) {
        $listenerAcquiredAtMs = $watch.ElapsedMilliseconds
      }
    }

    $readyNow = ($apiStatus -eq 200 -and $appStatus -eq 200 -and $govStatus -eq 200)
    if ($readyNow) {
      $okStreak += 1
      if ($okStreak -ge $RequiredConsecutive) {
        return [PSCustomObject]@{
          Ready = $true
          ElapsedMs = $watch.ElapsedMilliseconds
          TransientFailures = $transientFailures
          HardFailures = $hardFailures
          UvicornPid = $uvicornPid
          UvicornSeenAtMs = $uvicornSeenAtMs
          ListenerAcquiredAtMs = $listenerAcquiredAtMs
          LastStatuses = $lastStatusLine
        }
      }
    } else {
      $okStreak = 0
      if ($apiStatus -eq -1 -or $appStatus -eq -1 -or $govStatus -eq -1) {
        $transientFailures += 1
      } else {
        $hardFailures += 1
      }
    }

    $elapsedSeconds = [int]($watch.ElapsedMilliseconds / 1000)
    foreach ($checkpoint in $escalationCheckpoints) {
      if (-not $escalationLogged[$checkpoint] -and $elapsedSeconds -ge $checkpoint) {
        $escalationLogged[$checkpoint] = $true
        Write-Host "[Amicor Dev] Startup still settling after ${checkpoint}s ($lastStatusLine; transient=$transientFailures; hard=$hardFailures)"
      }
    }

    Start-Sleep -Milliseconds 500
  }

  return [PSCustomObject]@{
    Ready = $false
    ElapsedMs = $watch.ElapsedMilliseconds
    TransientFailures = $transientFailures
    HardFailures = $hardFailures
    UvicornPid = $uvicornPid
    UvicornSeenAtMs = $uvicornSeenAtMs
    ListenerAcquiredAtMs = $listenerAcquiredAtMs
    LastStatuses = $lastStatusLine
  }
}

function Write-RuntimeDiagnostic {
  param(
    [string]$Event,
    [hashtable]$Data
  )

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

$stateDir = Join-Path $repoRoot ".runtime"
$stateFile = Join-Path $stateDir "canonical_runtime_state.json"
$runtimeOutLog = Join-Path $stateDir "canonical_runtime.out.log"
$runtimeErrLog = Join-Path $stateDir "canonical_runtime.err.log"
$venvActivate = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not $env:VIRTUAL_ENV -and (Test-Path $venvActivate)) {
  & $venvActivate
}

$pythonExe = if (Test-Path $venvPython) { $venvPython } else { "python" }

$baseUrl = "http://$BindAddress`:$Port"
$appUrl = "$baseUrl/app"
$governanceUrl = "$baseUrl/app/operations/governance"
$apiHealthUrl = "$baseUrl/api/health"

if ($Restart) {
  & (Join-Path $PSScriptRoot "dev_down.ps1") -BindAddress $BindAddress -Port $Port | Out-Host
}

$healthStatus = Get-HealthStatus -Url $apiHealthUrl

if (Test-Path $stateFile) {
  try {
    $state = Get-Content $stateFile -Raw | ConvertFrom-Json
    $launcherPid = [int]$state.launcher_pid
    $statePort = if ($state.PSObject.Properties.Name -contains "port") { [int]$state.port } else { 0 }
    $alive = Test-ProcessAlive -ProcessId $launcherPid

    if ($alive -and $statePort -eq $Port -and $healthStatus -eq 200) {
      Write-Host "[Amicor Dev] Canonical runtime already healthy. Reusing existing runtime."
      Write-Host "[Amicor Dev] PID: $launcherPid"
      Write-Host $appUrl
      Write-Host $governanceUrl
      Write-Host $apiHealthUrl
      exit 0
    }

    if (-not $alive) {
      Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    }
  } catch {
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
  }
}

if ($healthStatus -eq 200) {
  Write-Host "[Amicor Dev] Runtime already reachable on canonical port $Port."
  Write-Host "[Amicor Dev] No duplicate runtime started."
  Write-Host $appUrl
  Write-Host $governanceUrl
  Write-Host $apiHealthUrl
  exit 0
}

if (-not (Test-Path $stateDir)) {
  New-Item -ItemType Directory -Path $stateDir | Out-Null
}

if ($healthStatus -ne 200) {
  $listenerPids = Get-VerifiedPortOwners -Port $Port

  foreach ($listenPid in $listenerPids) {
    if (-not $listenPid) { continue }
    try {
      Write-Host "[Amicor Dev] Clearing stale listener PID $listenPid on port $Port"
      Stop-Process -Id $listenPid -Force -ErrorAction Stop
    } catch {}
  }
}

$releaseCheck = Wait-ForPortRelease -Port $Port -TimeoutSeconds 20 -RequiredConsecutive 3
Write-Host "[Amicor Dev] Port release wait: released=$($releaseCheck.Released) elapsed_ms=$($releaseCheck.ElapsedMs)"
if (-not $releaseCheck.Released) {
  $owners = if ($releaseCheck.LastOwners) { ($releaseCheck.LastOwners -join ",") } else { "none" }
  Write-Host "[Amicor Dev] Port $Port did not fully release before startup. owners=$owners"
  Write-RuntimeDiagnostic -Event "startup.port_release_timeout" -Data @{
    port = $Port
    elapsed_ms = $releaseCheck.ElapsedMs
    owners = $owners
  }
  exit 1
}

$env:AMICOR_HOST = $BindAddress
$env:AMICOR_PORT = [string]$Port
$env:AMICOR_LOG_LEVEL = $LogLevel
$env:AMICOR_RELOAD = if ($Reload) { "1" } else { "0" }

Write-Host "[Amicor Dev] Starting canonical runtime on $baseUrl ..."

if (Test-Path $runtimeOutLog) { Remove-Item $runtimeOutLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $runtimeErrLog) { Remove-Item $runtimeErrLog -Force -ErrorAction SilentlyContinue }

$launcher = $null
$ready = $false

$listenerAcquiredMs = $null
$readinessMs = $null
$startupTransientFailures = 0
$startupHardFailures = 0

for ($attempt = 1; $attempt -le 2; $attempt++) {
  $attemptWatch = [System.Diagnostics.Stopwatch]::StartNew()
  $launcher = Start-Process -FilePath $pythonExe -ArgumentList "scripts/run_ops_runtime.py" -PassThru -WindowStyle Hidden -WorkingDirectory $repoRoot -RedirectStandardOutput $runtimeOutLog -RedirectStandardError $runtimeErrLog

  $attemptReady = Wait-ForConsecutiveReadiness -ApiHealthUrl $apiHealthUrl -AppUrl $appUrl -GovernanceUrl $governanceUrl -StateFile $stateFile -Port $Port -TimeoutSeconds 90 -RequiredConsecutive 2
  $startupTransientFailures += [int]$attemptReady.TransientFailures
  $startupHardFailures += [int]$attemptReady.HardFailures

  if ($attemptReady.Ready) {
    $secondPass = Wait-ForConsecutiveReadiness -ApiHealthUrl $apiHealthUrl -AppUrl $appUrl -GovernanceUrl $governanceUrl -StateFile $stateFile -Port $Port -TimeoutSeconds 8 -RequiredConsecutive 2
    if ($secondPass.Ready) {
      $ready = $true
      $listenerAcquiredMs = if ($attemptReady.ListenerAcquiredAtMs) { $attemptReady.ListenerAcquiredAtMs } else { $secondPass.ListenerAcquiredAtMs }
      $readinessMs = $attemptReady.ElapsedMs
      Write-RuntimeDiagnostic -Event "startup.success" -Data @{
        attempt = $attempt
        startup_ms = $startupStopwatch.ElapsedMilliseconds
        readiness_ms = $readinessMs
        listener_acquired_ms = $listenerAcquiredMs
        uvicorn_pid = $attemptReady.UvicornPid
        transient_failures = $startupTransientFailures
        hard_failures = $startupHardFailures
      }
      break
    }

    Write-Host "[Amicor Dev] Second-pass readiness confirmation failed; retrying startup."
  }

  $attemptExitedEarly = ($launcher -and $launcher.HasExited)

  if ($launcher -and -not $launcher.HasExited) {
    try { Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue } catch {}
  }

  if ($attempt -lt 2) {
    Write-Host "[Amicor Dev] Canonical startup attempt $attempt failed; retrying once after listener cleanup..."
    $retryPids = Get-VerifiedPortOwners -Port $Port

    foreach ($retryPid in $retryPids) {
      if (-not $retryPid) { continue }
      try {
        Write-Host "[Amicor Dev] Clearing listener PID $retryPid on port $Port before retry"
        Stop-Process -Id $retryPid -Force -ErrorAction Stop
      } catch {}
    }

    $releaseRetry = Wait-ForPortRelease -Port $Port -TimeoutSeconds 20 -RequiredConsecutive 3
    if (-not $releaseRetry.Released) {
      $owners = if ($releaseRetry.LastOwners) { ($releaseRetry.LastOwners -join ",") } else { "none" }
      Write-Host "[Amicor Dev] Retry aborted: port release timeout on $Port (owners=$owners)."
      Write-RuntimeDiagnostic -Event "startup.retry_port_release_timeout" -Data @{
        port = $Port
        attempt = $attempt
        elapsed_ms = $releaseRetry.ElapsedMs
        owners = $owners
      }
      exit 1
    }

    Start-Sleep -Milliseconds 600
    continue
  }

  if ($attemptExitedEarly) {
    Write-Host "[Amicor Dev] Runtime launcher exited early (code=$($launcher.ExitCode))."
  } else {
    Write-Host "[Amicor Dev] Canonical runtime failed to reach stable ready state on port $Port."
  }

  Write-Host "[Amicor Dev] Readiness diagnostics: transient_failures=$startupTransientFailures hard_failures=$startupHardFailures last_statuses=$($attemptReady.LastStatuses)"
  Write-RuntimeDiagnostic -Event "startup.failed" -Data @{
    port = $Port
    startup_ms = $startupStopwatch.ElapsedMilliseconds
    transient_failures = $startupTransientFailures
    hard_failures = $startupHardFailures
    last_statuses = $attemptReady.LastStatuses
    launcher_exited = $attemptExitedEarly
  }

  if (Test-Path $runtimeOutLog) {
    $tail = Get-Content $runtimeOutLog -Tail 12 -ErrorAction SilentlyContinue
    if ($tail) {
      Write-Host "[Amicor Dev] Launcher output tail:"
      $tail | ForEach-Object { Write-Host $_ }
    }
  }
  if (Test-Path $runtimeErrLog) {
    $etail = Get-Content $runtimeErrLog -Tail 12 -ErrorAction SilentlyContinue
    if ($etail) {
      Write-Host "[Amicor Dev] Launcher error tail:"
      $etail | ForEach-Object { Write-Host $_ }
    }
  }
  exit 1
}

if (-not $ready) {
  exit 1
}

Write-Host "[Amicor Dev] Startup timing: total_ms=$($startupStopwatch.ElapsedMilliseconds) readiness_ms=$readinessMs listener_acquired_ms=$listenerAcquiredMs"
Write-Host "[Amicor Dev] Canonical runtime is ready."
Write-Host "[Amicor Dev] Launcher PID: $($launcher.Id)"
Write-Host $appUrl
Write-Host $governanceUrl
Write-Host $apiHealthUrl
