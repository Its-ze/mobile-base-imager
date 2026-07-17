$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\ZSkeens\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$Venv = Join-Path $env:LOCALAPPDATA "MobileBaseImagerTooling\venv"
if (-not (Test-Path -LiteralPath (Join-Path $Venv "Scripts\python.exe"))) {
  & $Python -m venv $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install -r (Join-Path $Root "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
& $VenvPython (Join-Path $Root "scripts\generate-assets.py")
