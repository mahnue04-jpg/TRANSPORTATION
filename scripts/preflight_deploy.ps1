# Pre-deploy smoke checks for local stacks (no secrets required).
$ErrorActionPreference = "Continue"
$python = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"

$checks = @(
  @{ Name = "Python /api/health";           Url = "http://127.0.0.1:8010/api/health";           Expect = 200 },
  @{ Name = "Python /app/drivers";           Url = "http://127.0.0.1:8010/app/drivers";           Expect = 200 },
  @{ Name = "Python /app/dashboard";         Url = "http://127.0.0.1:8010/app/dashboard";         Expect = 200 },
  @{ Name = "nova-stable /api/health";      Url = "http://127.0.0.1:8011/api/health";           Expect = 200 },
  @{ Name = "nova-stable /dispatcher";       Url = "http://127.0.0.1:8011/dispatcher";           Expect = 200 },
  @{ Name = "nova-stable /driver";           Url = "http://127.0.0.1:8011/driver";               Expect = 200 }
)

Write-Host "=== Amicor deploy preflight ===" -ForegroundColor Cyan
$passed = 0
$failed = 0

foreach ($c in $checks) {
  try {
    $r = Invoke-WebRequest -Uri $c.Url -UseBasicParsing -TimeoutSec 20
    if ([int]$r.StatusCode -eq $c.Expect) {
      Write-Host "[PASS] $($c.Name)" -ForegroundColor Green
      $passed++
    } else {
      Write-Host "[FAIL] $($c.Name) - status $($r.StatusCode)" -ForegroundColor Red
      $failed++
    }
  } catch {
    Write-Host "[FAIL] $($c.Name) - $($_.Exception.Message)" -ForegroundColor Red
    $failed++
  }
}

if (Test-Path $python) {
  & $python -c @"
import urllib.request, urllib.error, json
try:
    urllib.request.urlopen('http://127.0.0.1:8010/api/health/readiness', timeout=15)
    print('[INFO] Python readiness: reachable (200)')
except urllib.error.HTTPError as e:
    body = json.loads(e.read().decode())
    print('[INFO] Python readiness:', body.get('overall_status'), 'score', body.get('score'))
    if body.get('overall_status') == 'not_ready':
        print('[WARN] Set DATABASE_URL + secrets on Render before production deploy')
"@ 
}

Write-Host ""
Write-Host "Passed: $passed  Failed: $failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Yellow" })
if ($failed -gt 0) {
  Write-Host "Start servers: .\scripts\start_both_local.ps1" -ForegroundColor Yellow
  exit 1
}
exit 0
