param(
  [string]$Version = "",
  [string]$Distro = "Ubuntu",
  [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim() }
if (-not $SkipCompile) {
  $LinuxRoot = (& wsl.exe -d $Distro -- wslpath -a $Root).Trim()
  if (-not $LinuxRoot) { throw "Could not resolve the project path inside WSL." }
  & wsl.exe -d $Distro -- bash "$LinuxRoot/scripts/build-linux.sh" $LinuxRoot $Version
  if ($LASTEXITCODE -ne 0) { throw "Linux release build failed." }
}

$Dist = Join-Path $Root "dist"
$assets = @(
  (Join-Path $Dist "mobile-base-imager-v$Version-windows-x64.exe"),
  (Join-Path $Dist "mobile-base-imager-v$Version-windows-x64.zip"),
  (Join-Path $Dist "mobile-base-imager-v$Version-linux-x86_64"),
  (Join-Path $Dist "mobile-base-imager-v$Version-linux-x86_64.tar.gz"),
  (Join-Path $Dist "mobile-base-imager_$($Version)_linux_amd64.deb"),
  (Join-Path $Dist "Mobile_Base_Imager-$Version-x86_64.AppImage"),
  (Join-Path $Dist "install-mobile-base-imager.sh"),
  (Join-Path $Dist "mobile-base-pi5-0.8.1.img.zst")
) | Where-Object { Test-Path -LiteralPath $_ }
$lines = foreach ($asset in $assets) {
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
  "$hash  $(Split-Path -Leaf $asset)"
}
[IO.File]::WriteAllText((Join-Path $Dist "checksums.txt"), ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
& (Join-Path $PSScriptRoot "build-pages.ps1") -Version $Version
Write-Host "Windows and Linux checksums and Pages metadata are ready."
