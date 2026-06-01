param(
  [string]$TaskName = "AmicorProductionRuntime"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$startupLauncher = Join-Path $startupDir "$TaskName.cmd"
$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

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

if (Test-Path $runKeyPath) {
  $runEntry = Get-ItemProperty -Path $runKeyPath -Name $TaskName -ErrorAction SilentlyContinue
  if ($null -ne $runEntry) {
    Remove-ItemProperty -Path $runKeyPath -Name $TaskName -ErrorAction SilentlyContinue
    Write-Host "[Amicor Prod] HKCU Run entry removed: $TaskName"
  }
}

exit 0
