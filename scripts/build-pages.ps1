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
$ImageVersion = "0.9.4"
$ImageAsset = "mobile-base-pi5-$ImageVersion.img.zst"
$Image = Join-Path $Root "dist\$ImageAsset"
$Exe = Join-Path $Root "dist\mobile-base-imager-v$Version-windows-x64.exe"
$Zip = Join-Path $Root "dist\mobile-base-imager-v$Version-windows-x64.zip"
$LinuxBinary = Join-Path $Root "dist\mobile-base-imager-v$Version-linux-x86_64"
$LinuxTar = Join-Path $Root "dist\mobile-base-imager-v$Version-linux-x86_64.tar.gz"
$LinuxDeb = Join-Path $Root "dist\mobile-base-imager_$($Version)_linux_amd64.deb"
$LinuxAppImage = Join-Path $Root "dist\Mobile_Base_Imager-$Version-x86_64.AppImage"
$LinuxInstaller = Join-Path $Root "dist\install-mobile-base-imager.sh"
if (Test-Path -LiteralPath $LinuxInstaller) {
  Copy-Item -LiteralPath $LinuxInstaller -Destination (Join-Path $Docs "install-mobile-base-imager.sh") -Force
}
$manifest = [ordered]@{
  appVersion = $Version
  imageVersion = $ImageVersion
  imageAsset = $ImageAsset
  imageUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/$ImageAsset"
  imageBytes = if (Test-Path -LiteralPath $Image) { (Get-Item -LiteralPath $Image).Length } else { 0 }
  imageSha256 = if (Test-Path -LiteralPath $Image) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Image).Hash } else { "" }
  exeUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-windows-x64.exe"
  exeBytes = if (Test-Path -LiteralPath $Exe) { (Get-Item -LiteralPath $Exe).Length } else { 0 }
  exeSha256 = if (Test-Path -LiteralPath $Exe) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Exe).Hash } else { "" }
  zipUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-windows-x64.zip"
  zipBytes = if (Test-Path -LiteralPath $Zip) { (Get-Item -LiteralPath $Zip).Length } else { 0 }
  linuxUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-linux-x86_64.tar.gz"
  linuxBytes = if (Test-Path -LiteralPath $LinuxTar) { (Get-Item -LiteralPath $LinuxTar).Length } else { 0 }
  linuxSha256 = if (Test-Path -LiteralPath $LinuxTar) { (Get-FileHash -Algorithm SHA256 -LiteralPath $LinuxTar).Hash } else { "" }
  linuxBinaryUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager-v$Version-linux-x86_64"
  linuxBinaryBytes = if (Test-Path -LiteralPath $LinuxBinary) { (Get-Item -LiteralPath $LinuxBinary).Length } else { 0 }
  linuxDebUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/mobile-base-imager_$($Version)_linux_amd64.deb"
  linuxDebBytes = if (Test-Path -LiteralPath $LinuxDeb) { (Get-Item -LiteralPath $LinuxDeb).Length } else { 0 }
  linuxDebSha256 = if (Test-Path -LiteralPath $LinuxDeb) { (Get-FileHash -Algorithm SHA256 -LiteralPath $LinuxDeb).Hash } else { "" }
  linuxAppImageUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/Mobile_Base_Imager-$Version-x86_64.AppImage"
  linuxAppImageBytes = if (Test-Path -LiteralPath $LinuxAppImage) { (Get-Item -LiteralPath $LinuxAppImage).Length } else { 0 }
  linuxAppImageSha256 = if (Test-Path -LiteralPath $LinuxAppImage) { (Get-FileHash -Algorithm SHA256 -LiteralPath $LinuxAppImage).Hash } else { "" }
  linuxInstallerUrl = "https://github.com/Its-ze/mobile-base-imager/releases/download/v$Version/install-mobile-base-imager.sh"
  linuxInstallerBytes = if (Test-Path -LiteralPath $LinuxInstaller) { (Get-Item -LiteralPath $LinuxInstaller).Length } else { 0 }
  linuxInstallerSha256 = if (Test-Path -LiteralPath $LinuxInstaller) { (Get-FileHash -Algorithm SHA256 -LiteralPath $LinuxInstaller).Hash } else { "" }
  generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
[IO.File]::WriteAllText((Join-Path $Docs "release-manifest.json"), ($manifest | ConvertTo-Json -Depth 5) + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "GitHub Pages staged at $Docs"
