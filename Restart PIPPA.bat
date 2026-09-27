@echo off
setlocal
cd /d "%~dp0"

echo Checking for a previous PIPPA server...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\release_pippa_port.ps1" -Port 8501
if errorlevel 1 (
  echo.
  echo PIPPA could not safely clear port 8501. No unrelated process was stopped.
  pause
  exit /b 1
)

call "Start PIPPA.bat"
