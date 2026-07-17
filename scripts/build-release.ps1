param([string]$Version = "")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim() }
$Tooling = Join-Path $env:LOCALAPPDATA "MobileBaseImagerTooling\venv"
$Python = Join-Path $Tooling "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { & (Join-Path $PSScriptRoot "bootstrap.ps1") }
$Image = "F:\Dropbox\Dev Ops\Mobile Base\dist\image\mobile-base-pi5-0.8.0.img.zst"
$ImageChecksum = "$Image.sha256"
$ExpectedImageHash = "383F69782A91272B04D3C1AA396D5550DF952B4264112CC808865EA35D67505B"
if (-not (Test-Path -LiteralPath $Image)) { throw "Mobile Base image is missing: $Image" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Image).Hash -ne $ExpectedImageHash) { throw "Mobile Base image does not match the verified 0.8.0 release hash." }

& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& $Python (Join-Path $Root "scripts\generate-assets.py") | Out-Null
$Screenshot = Join-Path $Root "output\mobile-base-imager-ui.png"
& $Python -m app.mobile_base_imager --demo --page flash --screenshot $Screenshot
if ($LASTEXITCODE -ne 0) { throw "Application screenshot generation failed." }

$PyInstaller = Join-Path $Tooling "Scripts\pyinstaller.exe"
$Dist = Join-Path $Root "dist"
& $PyInstaller --noconfirm --clean --onefile --windowed --name MobileBaseImager --icon (Join-Path $Root "assets\mobile-base-imager.ico") --add-data "$(Join-Path $Root 'assets\mobile-base-imager.ico');assets" --paths $Root --distpath $Dist --workpath (Join-Path $Root "build") --specpath $Root (Join-Path $Root "app\mobile_base_imager.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$Stage = Join-Path $env:TEMP "MobileBaseImagerRelease-$PID"
$Package = Join-Path $Stage "Mobile Base Imager"
Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Package | Out-Null
$Exe = Join-Path $Dist "MobileBaseImager.exe"
$VersionedExe = Join-Path $Dist "mobile-base-imager-v$Version-windows-x64.exe"
Copy-Item -LiteralPath $Exe -Destination $VersionedExe -Force
Copy-Item -LiteralPath $VersionedExe -Destination (Join-Path $Package "MobileBaseImager.exe") -Force
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination (Join-Path $Package "README.txt") -Force
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination $Package -Force
$Zip = Join-Path $Dist "mobile-base-imager-v$Version-windows-x64.zip"
Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
$TempZip = Join-Path $Stage "mobile-base-imager-v$Version-windows-x64.zip"
Compress-Archive -LiteralPath $Package -DestinationPath $TempZip -Force
Copy-Item -LiteralPath $TempZip -Destination $Zip -Force
Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $Image -Destination (Join-Path $Dist "mobile-base-pi5-0.8.0.img.zst") -Force
Copy-Item -LiteralPath $ImageChecksum -Destination (Join-Path $Dist "mobile-base-pi5-0.8.0.img.zst.sha256") -Force

$assets = @($VersionedExe, $Zip, (Join-Path $Dist "mobile-base-pi5-0.8.0.img.zst"))
$lines = foreach ($asset in $assets) {
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
  "$hash  $(Split-Path -Leaf $asset)"
}
[IO.File]::WriteAllText((Join-Path $Dist "checksums.txt"), ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
& (Join-Path $PSScriptRoot "build-pages.ps1") -Version $Version
Write-Host "Release package ready: $Dist"
Get-Item -LiteralPath $VersionedExe, $Zip, (Join-Path $Dist "mobile-base-pi5-0.8.0.img.zst") | Select-Object Name,Length
