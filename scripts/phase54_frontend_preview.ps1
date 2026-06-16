param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8010
)

$ErrorActionPreference = "Stop"

$appUrl = "http://${HostName}:${Port}/app?voiceDiag=1&liveVerify=1"
$govUrl = "http://${HostName}:${Port}/app/operations/governance?voiceDiag=1&liveVerify=1"

Write-Host "[PHASE 54] Opening frontend preview surfaces..." -ForegroundColor Cyan
Write-Host "  $appUrl"
Write-Host "  $govUrl"
Start-Process $appUrl | Out-Null
Start-Process $govUrl | Out-Null
