# Starts PostgreSQL in Docker — no Windows installer required.
# Requires Docker Desktop (with WSL2) running.

$ErrorActionPreference = "Stop"
$containerName = "amicor-postgres"

$dockerBin = "C:\Program Files\Docker\Docker\resources\bin"
if (Test-Path $dockerBin) {
  $env:PATH = "$dockerBin;$env:PATH"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Error "Docker not found. Install Docker Desktop and ensure it is running."
}

Write-Host "Starting PostgreSQL container '$containerName' on localhost:5432 ..."

$existing = docker ps -a --filter "name=$containerName" --format "{{.Names}}" 2>$null
if ($existing -eq $containerName) {
  docker start $containerName | Out-Null
} else {
  docker run -d `
    --name $containerName `
    -e POSTGRES_USER=amicor `
    -e POSTGRES_PASSWORD=amicor_dev `
    -e POSTGRES_DB=amicor_nova `
    -p 5432:5432 `
    postgres:16-alpine | Out-Null
}

Write-Host "Waiting for PostgreSQL..."
Start-Sleep -Seconds 5

$envContent = @"
NODE_ENV=development
PORT=8011
DATABASE_URL=postgresql://amicor:amicor_dev@localhost:5432/amicor_nova
JWT_SECRET=amicor-nova-secret-2026
FRONTEND_URL=http://localhost:8011
STRIPE_SECRET_KEY=sk_test_placeholder
STRIPE_PUBLISHABLE_KEY=pk_test_placeholder
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=
SENDGRID_FROM_NAME=Amicor Nova
"@

Set-Content -Path (Join-Path $PSScriptRoot ".." ".env") -Value $envContent -Encoding UTF8
Write-Host "Updated nova-backend/.env"
Write-Host "Next: npm run setup && npm start"
