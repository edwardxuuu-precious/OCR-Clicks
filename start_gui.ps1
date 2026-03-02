$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  Write-Host "[ERROR] Virtual environment not found: .venv" -ForegroundColor Red
  Write-Host "Please run:" -ForegroundColor Yellow
  Write-Host "  py -3.11 -m venv .venv"
  Write-Host "  .venv\Scripts\python.exe -m pip install -r requirements.txt"
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host "[INFO] Launching OCR GUI with .venv Python..." -ForegroundColor Cyan
& $python ".\src\ocr_mouse_tester_gui.py"
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Host "[ERROR] GUI exited with code $exitCode" -ForegroundColor Red
  Read-Host "Press Enter to exit"
}
exit $exitCode
