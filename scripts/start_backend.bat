@echo off
setlocal

set REPO_ROOT=%~dp0..
cd /d "%REPO_ROOT%"

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python

if "%AMICOR_HOST%"=="" set AMICOR_HOST=127.0.0.1
if "%AMICOR_PORT%"=="" set AMICOR_PORT=8011
if "%AMICOR_RELOAD%"=="" set AMICOR_RELOAD=0
if "%AMICOR_LOG_LEVEL%"=="" set AMICOR_LOG_LEVEL=info

echo [Amicor Runtime] Starting persistent backend runtime...
echo [Amicor Runtime] App URL:        http://%AMICOR_HOST%:%AMICOR_PORT%/app
echo [Amicor Runtime] Governance URL: http://%AMICOR_HOST%:%AMICOR_PORT%/app/operations/governance
echo [Amicor Runtime] API Health URL: http://%AMICOR_HOST%:%AMICOR_PORT%/api/health
echo [Amicor Runtime] Press Ctrl+C to stop cleanly.

"%PYTHON_EXE%" scripts\run_ops_runtime.py

endlocal
