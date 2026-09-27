@echo off
setlocal
cd /d "%~dp0"

rem Local email-only identity is permitted only through this explicit development launcher.
set "PIPPA_LOCAL_DEMO=true"

rem Use a dedicated Python 3.12 environment. Older .venv folders may point
rem to a different Python installation and must not be selected by existence.
set "PIPPA_PYTHON=%CD%\.venv312\Scripts\python.exe"
if exist "%PIPPA_PYTHON%" goto check_environment

set "PIPPA_BOOTSTRAP_PYTHON="
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
  if not errorlevel 1 set "PIPPA_BOOTSTRAP_PYTHON=python"
)

rem Codex Desktop also provides Python 3.12 when it is not on PATH.
if not defined PIPPA_BOOTSTRAP_PYTHON (
  if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    set "PIPPA_BOOTSTRAP_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  )
)
if not defined PIPPA_BOOTSTRAP_PYTHON (
  echo PIPPA requires Python 3.12.14. Install it, then run this file again.
  pause
  exit /b 1
)

echo Preparing PIPPA's Python 3.12 environment...
"%PIPPA_BOOTSTRAP_PYTHON%" -m venv .venv312
if errorlevel 1 (
  echo PIPPA could not create its Python environment.
  pause
  exit /b 1
)

:check_environment
"%PIPPA_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
  echo PIPPA's .venv312 environment cannot run Python 3.12.
  pause
  exit /b 1
)

echo Checking that PIPPA's port is available...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(15); do { $listener = @(& netstat -ano -p tcp | Select-String '^\s*TCP\s+\S+:8501\s+\S+\s+LISTENING\s+\d+\s*$'); if (-not $listener) { exit 0 }; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo Port 8501 is still being used by another program.
  echo Close any other PIPPA command windows, wait 15 seconds, and run this launcher again.
  pause
  exit /b 1
)

"%PIPPA_PYTHON%" -c "import streamlit, supabase, pydantic_core" >nul 2>nul
if errorlevel 1 (
  echo Installing PIPPA's required packages...
  "%PIPPA_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo PIPPA could not install its required packages. Check the internet connection and try again.
    pause
    exit /b 1
  )
)

"%PIPPA_PYTHON%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
pause
