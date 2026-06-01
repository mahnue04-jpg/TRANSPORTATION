param(
  [string]$TaskName = "AmicorProductionRuntime"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$startupLauncher = Join-Path $startupDir "$TaskName.cmd"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
  Write-Host "[Amicor Prod] Scheduled task not found: $TaskName"
}

if ($existing) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "[Amicor Prod] Scheduled task removed: $TaskName"
}

if (Test-Path $startupLauncher) {
  Remove-Item -Force $startupLauncher
  Write-Host "[Amicor Prod] Startup-folder launcher removed: $startupLauncher"
}

exit 0
