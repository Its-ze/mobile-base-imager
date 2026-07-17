param([string]$Version = "")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim() }
$Docs = Join-Path $Root "docs"
$Assets = Join-Path $Docs "assets"
New-Item -ItemType Directory -Force -Path $Assets | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "assets\mobile-base-imager-mark.svg") -Destination (Join-Path $Assets "mobile-base-imager-mark.svg") -Force
if (Test-Path -LiteralPath (Join-Path $Root "output\mobile-base-imager-ui.png")) {
  Copy-Item -LiteralPath (Join-Path $Root "output\mobile-base-imager-ui.png") -Destination (Join-Path $Assets "mobile-base-imager-ui.png") -Force
}
$Image = Join-Path $Root "dist\mobile-base-pi5-0.8.0.img.zst"
$Exe = Join-Path $Root "dist\mobile-base-imager-v$Version-windows-x64.exe"
$Zip = Join-Path $Root "dist\mobile-base-imager-v$Version-windows-x64.zip"
$manifest = [ordered]@{
  appVersion = $Version
  imageVersion = "0.8.0"
  imageAsset = "mobile-base-pi5-0.8.0.img.zst"
  imageUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-pi5-0.8.0.img.zst"
  imageBytes = if (Test-Path -LiteralPath $Image) { (Get-Item -LiteralPath $Image).Length } else { 516990112 }
  imageSha256 = "383F69782A91272B04D3C1AA396D5550DF952B4264112CC808865EA35D67505B"
  exeUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-windows-x64.exe"
  exeBytes = if (Test-Path -LiteralPath $Exe) { (Get-Item -LiteralPath $Exe).Length } else { 0 }
  exeSha256 = if (Test-Path -LiteralPath $Exe) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash } else { "" }
  zipUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-windows-x64.zip"
  zipBytes = if (Test-Path -LiteralPath $Zip) { (Get-Item -LiteralPath $Zip).Length } else { 0 }
  generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
[IO.File]::WriteAllText((Join-Path $Docs "release-manifest.json"), ($manifest | ConvertTo-Json -Depth 5) + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "GitHub Pages staged at $Docs"
