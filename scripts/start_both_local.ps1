# Start Amicor Python (8010) + nova-stable (8011) for local ops testing.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$backend = Join-Path $repoRoot "backend"
$nova = Join-Path $repoRoot "nova-stable"

if (-not (Test-Path $python)) {
  throw "Python venv not found at $python — run python -m venv .venv and pip install -r backend/requirements.txt"
}

function Test-PortListening([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  return [bool]$conn
}

if (-not (Test-PortListening 8010)) {
  Write-Host "[Amicor] Starting Python backend on http://127.0.0.1:8010 ..."
  Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory $backend -WindowStyle Normal
} else {
  Write-Host "[Amicor] Port 8010 already in use — skipping Python start."
}

if (-not (Test-PortListening 8011)) {
  Write-Host "[Amicor] Starting nova-stable on http://127.0.0.1:8011 ..."
  Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "set JWT_SECRET=local-dev-secret&& set PORT=8011&& node server.js" -WorkingDirectory $nova -WindowStyle Normal
} else {
  Write-Host "[Amicor] Port 8011 already in use — skipping nova-stable start."
}

Write-Host ""
Write-Host "Open:"
Write-Host "  Full ops:     http://127.0.0.1:8010/app/dashboard"
Write-Host "  Drivers:      http://127.0.0.1:8010/app/drivers"
Write-Host "  Dispatch:     http://127.0.0.1:8011/dispatcher"
Write-Host ""
Write-Host "Run preflight:  .\scripts\preflight_deploy.ps1"
