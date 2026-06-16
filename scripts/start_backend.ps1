param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8011,
  [switch]$Reload,
  [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvActivate = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not $env:VIRTUAL_ENV -and (Test-Path $venvActivate)) {
  & $venvActivate
}

if (Test-Path $venvPython) {
  $pythonExe = $venvPython
} else {
  $pythonExe = "python"
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

function Get-HealthStatus {
  param([string]$Url)
  try {
    $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 4 -UseBasicParsing
    return [int]$response.StatusCode
  } catch {
    if ($_.Exception.Response) {
      return [int]$_.Exception.Response.StatusCode
    }
    return -1
  }
}

$env:AMICOR_HOST = $BindHost
$env:AMICOR_PORT = [string]$Port
$env:AMICOR_LOG_LEVEL = $LogLevel
$env:AMICOR_RELOAD = if ($Reload) { "1" } else { "0" }

$baseUrl = "http://$BindHost`:$Port"
Write-Host "[Amicor Runtime] Starting canonical backend runtime..."
Write-Host "[Amicor Runtime] App URL:        $baseUrl/app"
Write-Host "[Amicor Runtime] Governance URL: $baseUrl/app/operations/governance"
Write-Host "[Amicor Runtime] API Health URL: $baseUrl/api/health"

$healthUrl = "$baseUrl/api/health"
$healthStatus = Get-HealthStatus -Url $healthUrl
$listenerPids = Get-ListenerPids -TargetPort $Port

if ($healthStatus -eq 200 -and $listenerPids.Count -gt 0) {
  Write-Host "[Amicor Runtime] Runtime already healthy on port $Port (PID=$($listenerPids[0]))."
  exit 0
}

if ($listenerPids.Count -gt 0 -and $healthStatus -ne 200) {
  foreach ($stalePid in $listenerPids) {
    try {
      Write-Host "[Amicor Runtime] Stopping stale listener PID $stalePid on port $Port"
      Stop-Process -Id $stalePid -Force -ErrorAction Stop
    } catch {
      Write-Host "[Amicor Runtime] Unable to stop PID ${stalePid}: $($_.Exception.Message)"
    }
  }
}

Write-Host "[Amicor Runtime] Launching runtime supervisor..."
& $pythonExe "scripts/run_ops_runtime.py"
exit $LASTEXITCODE
