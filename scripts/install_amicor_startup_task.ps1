param(
  [string]$TaskName = "AmicorProductionRuntime",
  [string]$BindAddress = "0.0.0.0",
  [int]$Port = 8000,
  [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $repoRoot "scripts/start_amicor_prod.ps1"
if (-not (Test-Path $startScript)) {
  throw "Start script not found: $startScript"
}
$startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$startupLauncher = Join-Path $startupDir "$TaskName.cmd"

$command = "powershell.exe"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -BindAddress $BindAddress -Port $Port -LogLevel $LogLevel"

$action = New-ScheduledTaskAction -Execute $command -Argument $arguments -WorkingDirectory $repoRoot
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

try {
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest -LogonType ServiceAccount
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($triggerStartup, $triggerLogon) -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "[Amicor Prod] Scheduled task installed: $TaskName"
  Write-Host "[Amicor Prod] It will auto-start on boot and user logon."
  exit 0
} catch {
  Write-Warning "SYSTEM task registration failed: $($_.Exception.Message)"
  $startupContent = @"
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -BindAddress $BindAddress -Port $Port -LogLevel $LogLevel
"@
  Set-Content -Path $startupLauncher -Value $startupContent -Encoding ASCII
  Write-Host "[Amicor Prod] Startup-folder launcher installed: $startupLauncher"
  Write-Host "[Amicor Prod] It will auto-start on user logon. Boot-start requires elevated SYSTEM registration."
  exit 0
}
