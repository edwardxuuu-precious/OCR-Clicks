@echo off
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PowerShell not found. Please run start_gui.ps1 manually in PowerShell.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File ".\start_gui.ps1"
set "EXITCODE=%ERRORLEVEL%"
exit /b %EXITCODE%
