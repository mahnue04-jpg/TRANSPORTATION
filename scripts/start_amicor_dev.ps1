param(
  [switch]$NoBrowser,
  [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$startBackendScript = Join-Path $repoRoot "scripts/start_backend.ps1"
 $devUpScript = Join-Path $repoRoot "scripts/dev_up.ps1"
if (-not (Test-Path $startBackendScript)) {
  throw "Required script missing: $startBackendScript"
}
if (-not (Test-Path $devUpScript)) {
  throw "Required script missing: $devUpScript"
}

$canonicalHost = "127.0.0.1"
$canonicalPort = 8010
$canonicalFrontendUrl = "http://$canonicalHost`:$canonicalPort/app"
$canonicalBackendUrl = "http://$canonicalHost`:$canonicalPort"
$canonicalWebsocketUrl = "ws://$canonicalHost`:$canonicalPort/api/health-isf/ws/live"
$runtimeEnvironment = "development"
$frontendBuildVersion = "20260519.2"
$hydrationVersion = "20260519.2"
$startupWaitSeconds = 120

Write-Host "[Amicor Dev] Preparing canonical runtime..."
Write-Host "[Amicor Dev] Frontend URL:   $canonicalFrontendUrl"
Write-Host "[Amicor Dev] Backend URL:    $canonicalBackendUrl"
Write-Host "[Amicor Dev] WebSocket URL:  $canonicalWebsocketUrl"
Write-Host "[Amicor Dev] Environment:    $runtimeEnvironment"
Write-Host "[Amicor Dev] Build Version:  $frontendBuildVersion"
Write-Host "[Amicor Dev] Hydration Ver.: $hydrationVersion"

$env:AMICOR_CANONICAL_FRONTEND_URL = $canonicalFrontendUrl
$env:AMICOR_BACKEND_URL = $canonicalBackendUrl
$env:AMICOR_WEBSOCKET_URL = $canonicalWebsocketUrl
$env:AMICOR_ENVIRONMENT = $runtimeEnvironment
$env:AMICOR_FRONTEND_BUILD_VERSION = $frontendBuildVersion
$env:AMICOR_HYDRATION_VERSION = $hydrationVersion

function Wait-ForHealth {
  param(
    [string]$Url,
    [int]$TimeoutSeconds = 30
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
      if ([int]$response.StatusCode -eq 200) {
        return $true
      }
    } catch {
    }

    Start-Sleep -Seconds 1
  }

  return $false
}

function Open-BrowserWithRetry {
  param(
    [string]$Url,
    [int]$Attempts = 3,
    [int]$DelaySeconds = 2
  )

  for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
      Start-Process $Url -ErrorAction Stop | Out-Null
      return $true
    } catch {
      if ($attempt -eq $Attempts) {
        throw "Failed to open browser after $Attempts attempts for $Url. Last error: $($_.Exception.Message)"
      }
      Write-Host "[Amicor Dev] Browser launch attempt $attempt failed. Retrying..."
      Start-Sleep -Seconds $DelaySeconds
    }
  }

  return $false
}

& $devUpScript -BindAddress $canonicalHost -Port $canonicalPort -Reload:(-not $NoReload) -LogLevel "info"
if ($LASTEXITCODE -ne 0) {
  throw "Canonical runtime startup failed (exit code $LASTEXITCODE)."
}

if (-not (Wait-ForHealth -Url "$canonicalBackendUrl/api/health" -TimeoutSeconds $startupWaitSeconds)) {
  throw "Canonical runtime did not report healthy on $canonicalBackendUrl/api/health within $startupWaitSeconds seconds."
}

if (-not (Wait-ForHealth -Url $canonicalFrontendUrl -TimeoutSeconds $startupWaitSeconds)) {
  throw "Canonical runtime did not report healthy on $canonicalFrontendUrl within $startupWaitSeconds seconds."
}

if (-not $NoBrowser) {
  Open-BrowserWithRetry -Url $canonicalFrontendUrl -Attempts 3 -DelaySeconds 2 | Out-Null
}

Write-Host "[Amicor Dev] Runtime ready at $canonicalFrontendUrl"
