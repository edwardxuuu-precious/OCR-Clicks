$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$reqHashFile = Join-Path $PSScriptRoot ".venv\.requirements.sha256"
$importCheck = "import importlib.util,sys;mods=['mss','numpy','cv2','rapidocr_onnxruntime','pyautogui'];missing=[m for m in mods if importlib.util.find_spec(m) is None];print('MISSING:'+','.join(missing)) if missing else None;sys.exit(1 if missing else 0)"

function Get-PythonBootstrapCommand {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return @("py", "-3.11")
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return @("python")
  }
  return @()
}

function Ensure-Venv {
  if (Test-Path $venvPython) {
    return
  }
  Write-Host "[SETUP] .venv not found. Creating virtual environment..." -ForegroundColor Yellow
  $bootstrap = Get-PythonBootstrapCommand
  if ($bootstrap.Count -eq 0) {
    Write-Host "[ERROR] Python not found. Install Python 3.11+ first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
  }

  if ($bootstrap.Count -eq 2) {
    & $bootstrap[0] $bootstrap[1] -m venv .venv
  } else {
    & $bootstrap[0] -m venv .venv
  }

  if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Failed to create .venv" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
  }
}

function Get-RequirementsHash {
  if (-not (Test-Path $requirements)) {
    return ""
  }
  return (Get-FileHash $requirements -Algorithm SHA256).Hash.ToLower()
}

function Read-InstalledRequirementsHash {
  if (-not (Test-Path $reqHashFile)) {
    return ""
  }
  try {
    return (Get-Content $reqHashFile -Raw).Trim().ToLower()
  } catch {
    return ""
  }
}

function Test-DependenciesInstalled {
  & $venvPython -c $importCheck | Out-Host
  return ($LASTEXITCODE -eq 0)
}

function Install-Dependencies {
  if (-not (Test-Path $requirements)) {
    Write-Host "[ERROR] requirements.txt not found." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
  }
  Write-Host "[SETUP] Installing dependencies from requirements.txt..." -ForegroundColor Yellow
  & $venvPython -m pip install --disable-pip-version-check -r $requirements
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
  }
}

Ensure-Venv

$requiredHash = Get-RequirementsHash
$installedHash = Read-InstalledRequirementsHash
$needInstall = $false

if ($requiredHash -eq "") {
  Write-Host "[WARN] requirements.txt missing. Continue without dependency bootstrap." -ForegroundColor Yellow
} elseif ($requiredHash -ne $installedHash) {
  $needInstall = $true
  Write-Host "[SETUP] Dependency lock changed (or first run). Will sync dependencies..." -ForegroundColor Yellow
} elseif (-not (Test-DependenciesInstalled)) {
  $needInstall = $true
  Write-Host "[SETUP] Missing runtime dependencies detected. Will repair install..." -ForegroundColor Yellow
}

if ($needInstall) {
  Install-Dependencies
  if ($requiredHash -ne "") {
    Set-Content -Path $reqHashFile -Value $requiredHash -NoNewline
  }
  if (-not (Test-DependenciesInstalled)) {
    Write-Host "[ERROR] Dependency check still failed after install." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
  }
}

Write-Host "[INFO] Launching OCR GUI..." -ForegroundColor Cyan
& $venvPython ".\src\ocr_mouse_tester_gui.py"
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Host "[ERROR] GUI exited with code $exitCode" -ForegroundColor Red
  Read-Host "Press Enter to exit"
}
exit $exitCode
