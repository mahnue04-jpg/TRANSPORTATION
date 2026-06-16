param(
  [string]$BindAddress = "0.0.0.0",
  [int]$Port = 8000,
  [string]$LogLevel = "info",
  [int]$RestartDelaySeconds = 5,
  [int]$StartupTimeoutSeconds = 120,
  [int]$HealthIntervalSeconds = 15,
  [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runtimeDir = Join-Path $repoRoot ".runtime"
if (-not (Test-Path $runtimeDir)) {
  New-Item -Path $runtimeDir -ItemType Directory | Out-Null
}

$watchdogStateFile = Join-Path $runtimeDir "prod_watchdog_state.json"
$watchdogLogFile = Join-Path $runtimeDir "prod_watchdog.log"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
  $pythonExe = $venvPython
} else {
  $pythonExe = "python"
}

$env:AMICOR_HOST = $BindAddress
$env:AMICOR_PORT = [string]$Port
$env:AMICOR_LOG_LEVEL = $LogLevel
$env:AMICOR_RELOAD = "0"
$env:AMICOR_STARTUP_TIMEOUT = [string]$StartupTimeoutSeconds
$env:AMICOR_HEALTH_INTERVAL = [string]$HealthIntervalSeconds

$databaseUrl = $env:DATABASE_URL
if ($databaseUrl -and $databaseUrl.StartsWith("sqlite:///./")) {
  $relativePath = $databaseUrl.Substring("sqlite:///./".Length)
  $absolutePath = Join-Path $repoRoot $relativePath
  $absolutePath = $absolutePath -replace "\\", "/"
  $env:DATABASE_URL = "sqlite:///$absolutePath"
}

function Write-WatchdogLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
  Add-Content -Path $watchdogLogFile -Value $line -Encoding UTF8
  Write-Host $line
}

function Write-WatchdogState {
  param(
    [string]$Mode,
    [int]$Attempt,
    [int]$LastExitCode,
    [string]$Status
  )
  $payload = [ordered]@{
    mode = $Mode
    watchdog_pid = $PID
    bind_address = $BindAddress
    port = $Port
    log_level = $LogLevel
    no_restart = [bool]$NoRestart
    restart_delay_seconds = $RestartDelaySeconds
    startup_timeout_seconds = $StartupTimeoutSeconds
    health_interval_seconds = $HealthIntervalSeconds
    attempt = $Attempt
    last_exit_code = $LastExitCode
    status = $Status
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $watchdogStateFile -Encoding UTF8
}

Write-WatchdogLog "watchdog starting pid=$PID bind=$BindAddress port=$Port no_restart=$([bool]$NoRestart)"
$attempt = 0
$lastExitCode = 0

while ($true) {
  $attempt += 1
  Write-WatchdogState -Mode "starting" -Attempt $attempt -LastExitCode $lastExitCode -Status "launching_runtime"
  Write-WatchdogLog "launch attempt=$attempt"

  & $pythonExe "scripts/run_ops_runtime.py"
  $lastExitCode = $LASTEXITCODE

  Write-WatchdogState -Mode "post_run" -Attempt $attempt -LastExitCode $lastExitCode -Status "runtime_exited"
  Write-WatchdogLog "runtime exited with code=$lastExitCode"

  if ($NoRestart) {
    Write-WatchdogLog "no-restart mode enabled; watchdog exiting"
    break
  }

  if ($lastExitCode -eq 0) {
    Write-WatchdogLog "runtime performed clean shutdown; waiting $RestartDelaySeconds seconds then relaunching"
  } else {
    Write-WatchdogLog "runtime crash detected; waiting $RestartDelaySeconds seconds before restart"
  }

  Start-Sleep -Seconds $RestartDelaySeconds
}

Write-WatchdogState -Mode "stopped" -Attempt $attempt -LastExitCode $lastExitCode -Status "watchdog_stopped"
exit $lastExitCode
