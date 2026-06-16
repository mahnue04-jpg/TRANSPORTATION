param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8010,
  [switch]$OpenBrowser = $true,
  [switch]$StopConflictingPreviewRuntimes = $true
)

$ErrorActionPreference = "Stop"

function Write-Phase54Status {
  param(
    [string]$State,
    [string]$Message,
    [hashtable]$Extra
  )

  $runtimeDir = Join-Path $root ".runtime"
  if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
  }
  $statusPath = Join-Path $runtimeDir "phase54_preview_hotfix_status.json"
  $payload = [ordered]@{
    ts = (Get-Date).ToUniversalTime().ToString("o")
    state = $State
    message = $Message
    host = $HostName
    port = $Port
  }
  if ($Extra) {
    foreach ($k in $Extra.Keys) {
      $payload[$k] = $Extra[$k]
    }
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $statusPath -Encoding UTF8
}

function Get-PortOwners {
  param([int[]]$Ports)
  $rows = @()
  foreach ($p in $Ports) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
      $proc = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess) -ErrorAction SilentlyContinue
      $rows += [PSCustomObject]@{
        port = $p
        pid = $listener.OwningProcess
        name = if ($proc) { $proc.Name } else { $null }
        commandLine = if ($proc) { $proc.CommandLine } else { $null }
      }
    }
  }
  return $rows
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Phase54Status -State "failed" -Message "Missing virtualenv python executable" -Extra @{ expected = ".venv\\Scripts\\python.exe" }
  throw "Missing .venv Python interpreter. Create the venv before running preview."
}

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  & ".\.venv\Scripts\Activate.ps1"
}

$env:AMICOR_HOST = $HostName
$env:AMICOR_PORT = "$Port"

$candidatePorts = @($Port, 8010, 8011) | Select-Object -Unique
$portOwners = Get-PortOwners -Ports $candidatePorts

Write-Host "[PHASE 54] Port ownership before startup:" -ForegroundColor Cyan
if ($portOwners.Count -eq 0) {
  Write-Host "  (no listeners on $($candidatePorts -join ', '))"
} else {
  foreach ($row in $portOwners) {
    Write-Host "  port=$($row.port) pid=$($row.pid) name=$($row.name)"
  }
}

if ($StopConflictingPreviewRuntimes.IsPresent) {
  $conflicts = $portOwners | Where-Object {
    $_.port -ne $Port -and $_.name -eq "python.exe" -and [string]$_.commandLine -match "uvicorn\s+app\.main:app"
  }
  foreach ($conflict in $conflicts) {
    try {
      Write-Host "[PHASE 54] Stopping conflicting preview runtime on port $($conflict.port) (PID=$($conflict.pid))" -ForegroundColor Yellow
      Stop-Process -Id ([int]$conflict.pid) -Force -ErrorAction Stop
    } catch {
      Write-Host "[PHASE 54] Failed to stop conflicting PID $($conflict.pid): $($_.Exception.Message)" -ForegroundColor Red
    }
  }
}

Write-Host "[PHASE 54] Starting canonical preview runtime on ${HostName}:${Port}..." -ForegroundColor Cyan
Write-Phase54Status -State "starting" -Message "Launching canonical runtime via dev_up" -Extra @{ host = $HostName; port = $Port }
& ".\scripts\dev_up.ps1" -BindAddress $HostName -Port $Port

Write-Host "[PHASE 54] Running startup + route registration validation..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" ".\scripts\phase54_preview_validate.py"
if ($LASTEXITCODE -ne 0) {
  Write-Host "[PHASE 54] Initial validation failed; forcing runtime restart and re-validating..." -ForegroundColor Yellow
  Write-Phase54Status -State "recovering" -Message "Initial preview validation failed; retrying with forced restart" -Extra @{ exitCode = $LASTEXITCODE }

  & ".\scripts\dev_up.ps1" -BindAddress $HostName -Port $Port -Restart
  & ".\.venv\Scripts\python.exe" ".\scripts\phase54_preview_validate.py"

  if ($LASTEXITCODE -ne 0) {
    Write-Phase54Status -State "failed" -Message "Preview validation failed after forced restart" -Extra @{ exitCode = $LASTEXITCODE }
    throw "PHASE 54 preview validation failed after forced restart. Review diagnostics above."
  }
}

$appUrl = "http://${HostName}:${Port}/app?voiceDiag=1&liveVerify=1"
$govUrl = "http://${HostName}:${Port}/app/operations/governance?voiceDiag=1&liveVerify=1"
$apiUrl = "http://${HostName}:${Port}/api/health"

Write-Phase54Status -State "ready" -Message "Preview runtime validated" -Extra @{
  appUrl = $appUrl
  governanceUrl = $govUrl
  healthUrl = $apiUrl
}

Write-Host "[PHASE 54] Preview URLs:" -ForegroundColor Green
Write-Host "  App: $appUrl" -ForegroundColor Green
Write-Host "  Governance: $govUrl" -ForegroundColor Green
Write-Host "  API health: $apiUrl" -ForegroundColor Green

if ($OpenBrowser.IsPresent) {
  Start-Process $appUrl | Out-Null
}
