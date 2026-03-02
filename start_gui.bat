@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found: .venv
  echo Please run:
  echo   py -3.11 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo [INFO] Launching OCR GUI with .venv Python...
".venv\Scripts\python.exe" "src\ocr_mouse_tester_gui.py"
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo [ERROR] GUI exited with code %EXITCODE%.
  pause
)

exit /b %EXITCODE%
