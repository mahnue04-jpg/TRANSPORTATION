param(
  [string]$BindAddress = "127.0.0.1",
  [int]$Port = 8011,
  [switch]$Reload,
  [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $repoRoot ".runtime"
$restartLockPath = Join-Path $runtimeDir "dev_restart.lock"
$restartWatch = [System.Diagnostics.Stopwatch]::StartNew()

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
    [int]$TimeoutSeconds = 25,
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

function Get-HealthStatus {
  param([string]$Url)
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
    return [int]$response.StatusCode
  } catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return -1
  }
}

function Confirm-StableHealth {
  param([string]$HealthUrl, [int]$RequiredConsecutive = 2)
  $streak = 0
  for ($i = 0; $i -lt 8; $i++) {
    $status = Get-HealthStatus -Url $HealthUrl
    if ($status -eq 200) {
      $streak += 1
      if ($streak -ge $RequiredConsecutive) {
        return $true
      }
    } else {
      $streak = 0
    }
    Start-Sleep -Milliseconds 300
  }
  return $false
}

function Write-RuntimeDiagnostic {
  param([string]$Event,[hashtable]$Data)
  if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
  }
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

function Acquire-RestartLock {
  if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
  }

  if (Test-Path $restartLockPath) {
    try {
      $existing = Get-Content $restartLockPath -Raw | ConvertFrom-Json
      $existingPid = if ($existing.PSObject.Properties.Name -contains "pid") { [int]$existing.pid } else { 0 }
      if ($existingPid -gt 0 -and (Test-PidAliveByTasklist -ProcessId $existingPid)) {
        Write-Host "[Amicor Dev] Restart already in progress by PID $existingPid. Aborting overlap."
        return $false
      }
    } catch {}
    Remove-Item $restartLockPath -Force -ErrorAction SilentlyContinue
  }

  try {
    $stream = [System.IO.File]::Open($restartLockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.Write((@{ pid = $PID; started_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json -Compress))
    $writer.Flush()
    $writer.Dispose()
    $stream.Dispose()
    return $true
  } catch {
    Write-Host "[Amicor Dev] Could not acquire restart lock at $restartLockPath"
    return $false
  }
}

function Release-RestartLock {
  if (Test-Path $restartLockPath) {
    Remove-Item $restartLockPath -Force -ErrorAction SilentlyContinue
  }
}

if (-not (Acquire-RestartLock)) {
  exit 1
}

try {
  $healthUrl = "http://$BindAddress`:$Port/api/health"

  & (Join-Path $scriptDir "dev_down.ps1") -BindAddress $BindAddress -Port $Port
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[Amicor Dev] Shutdown step reported failure; aborting restart."
    Write-RuntimeDiagnostic -Event "restart.shutdown_failed" -Data @{ port = $Port; restart_ms = $restartWatch.ElapsedMilliseconds }
    exit 1
  }

  $clearResult = Wait-ForListenerClear -Port $Port -TimeoutSeconds 25 -RequiredConsecutive 3
  if (-not $clearResult.Cleared) {
    $owners = if ($clearResult.LastOwners) { ($clearResult.LastOwners -join ",") } else { "none" }
    Write-Host "[Amicor Dev] Restart aborted: previous listener did not fully exit (owners=$owners)."
    Write-RuntimeDiagnostic -Event "restart.listener_not_cleared" -Data @{
      port = $Port
      elapsed_ms = $clearResult.ElapsedMs
      owners = $owners
      restart_ms = $restartWatch.ElapsedMilliseconds
    }
    exit 1
  }

  $attemptDelaysMs = @(500, 1000, 2000)
  for ($attempt = 1; $attempt -le $attemptDelaysMs.Count; $attempt++) {
    & (Join-Path $scriptDir "dev_up.ps1") -BindAddress $BindAddress -Port $Port -Reload:$Reload -LogLevel $LogLevel
    if ($LASTEXITCODE -eq 0) {
      $ownersAfter = Get-VerifiedPortOwners -Port $Port
      $singleOwner = ($ownersAfter.Count -eq 1)
      $stableHealth = Confirm-StableHealth -HealthUrl $healthUrl -RequiredConsecutive 2

      if ($singleOwner -and $stableHealth) {
        Write-Host "[Amicor Dev] Restart succeeded with single listener ownership (pid=$($ownersAfter[0]))."
        Write-Host "[Amicor Dev] Restart timing: total_ms=$($restartWatch.ElapsedMilliseconds)"
        Write-RuntimeDiagnostic -Event "restart.success" -Data @{
          port = $Port
          attempt = $attempt
          owner_pid = $ownersAfter[0]
          restart_ms = $restartWatch.ElapsedMilliseconds
          listener_clear_ms = $clearResult.ElapsedMs
        }
        exit 0
      }

      $ownersText = if ($ownersAfter) { ($ownersAfter -join ",") } else { "none" }
      Write-Host "[Amicor Dev] Post-restart validation failed: single_owner=$singleOwner stable_health=$stableHealth owners=$ownersText"
      Write-RuntimeDiagnostic -Event "restart.post_validation_failed" -Data @{
        port = $Port
        attempt = $attempt
        single_owner = $singleOwner
        stable_health = $stableHealth
        owners = $ownersText
        restart_ms = $restartWatch.ElapsedMilliseconds
      }
    }

    if ($attempt -lt $attemptDelaysMs.Count) {
      $delayMs = [Math]::Min($attemptDelaysMs[$attempt - 1], 4000)
      Write-Host "[Amicor Dev] Restart attempt $attempt failed; backing off for ${delayMs}ms before retry."
      & (Join-Path $scriptDir "dev_down.ps1") -BindAddress $BindAddress -Port $Port | Out-Null
      $null = Wait-ForListenerClear -Port $Port -TimeoutSeconds 20 -RequiredConsecutive 2
      Start-Sleep -Milliseconds $delayMs
      continue
    }
  }

  Write-Host "[Amicor Dev] Restart failed after bounded retries."
  Write-RuntimeDiagnostic -Event "restart.failed" -Data @{
    port = $Port
    restart_ms = $restartWatch.ElapsedMilliseconds
  }
  exit 1
}
finally {
  Release-RestartLock
}
