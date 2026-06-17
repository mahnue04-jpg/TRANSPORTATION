# Push nova-backend to https://github.com/mahnue04-jpg/TRANSPORTATION for Render deploy.
# Requires: git, GitHub auth (gh auth login or credential manager)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
$Nova = Join-Path $RepoRoot "nova-backend"
$TransportUrl = "https://github.com/mahnue04-jpg/TRANSPORTATION.git"
$Work = Join-Path $env:TEMP "transportation-deploy-$(Get-Random)"

Write-Host "Source: $Nova"
Write-Host "Staging: $Work"

git clone $TransportUrl $Work
New-Item -ItemType Directory -Force -Path (Join-Path $Work "nova-backend") | Out-Null

$exclude = @("node_modules", ".env", "*.db")
Get-ChildItem $Nova -Force | Where-Object {
    $_.Name -notin @("node_modules", ".env") -and $_.Name -notlike "*.db"
} | ForEach-Object {
    Copy-Item $_.FullName -Destination (Join-Path $Work "nova-backend\$($_.Name)") -Recurse -Force
}

Push-Location $Work
git add -A
git status --short
if (-not (git diff --cached --quiet 2>$null)) {
    git commit -m "Add nova-backend for Render deploy (SQLite stable)"
    git push origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push failed. Log in as mahnue04-jpg (not support728) and retry."
        Pop-Location
        exit 1
    }
    Write-Host "Pushed to TRANSPORTATION. Redeploy on Render."
} else {
    Write-Host "No changes to push."
}
Pop-Location
Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
