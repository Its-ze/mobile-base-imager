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
  $LinuxScript = 'bash "$MBI_LINUX_ROOT/scripts/build-linux.sh" "$MBI_LINUX_ROOT" "$MBI_VERSION"'
  $Payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($LinuxScript))
  $PreviousRoot = [Environment]::GetEnvironmentVariable("MBI_LINUX_ROOT", "Process")
  $PreviousVersion = [Environment]::GetEnvironmentVariable("MBI_VERSION", "Process")
  $PreviousWslEnv = [Environment]::GetEnvironmentVariable("WSLENV", "Process")
  try {
    [Environment]::SetEnvironmentVariable("MBI_LINUX_ROOT", $LinuxRoot, "Process")
    [Environment]::SetEnvironmentVariable("MBI_VERSION", $Version, "Process")
    $Forwarded = @("MBI_LINUX_ROOT", "MBI_VERSION", $PreviousWslEnv) | Where-Object { $_ }
    [Environment]::SetEnvironmentVariable("WSLENV", ($Forwarded -join ":"), "Process")
    & wsl.exe -d $Distro -- bash -lc "echo $Payload | base64 -d | bash"
  } finally {
    [Environment]::SetEnvironmentVariable("MBI_LINUX_ROOT", $PreviousRoot, "Process")
    [Environment]::SetEnvironmentVariable("MBI_VERSION", $PreviousVersion, "Process")
    [Environment]::SetEnvironmentVariable("WSLENV", $PreviousWslEnv, "Process")
  }
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
  (Join-Path $Dist "mobile-base-pi5-0.9.2.img.zst")
) | Where-Object { Test-Path -LiteralPath $_ }
$lines = foreach ($asset in $assets) {
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
  "$hash  $(Split-Path -Leaf $asset)"
}
[IO.File]::WriteAllText((Join-Path $Dist "checksums.txt"), ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
& (Join-Path $PSScriptRoot "build-pages.ps1") -Version $Version
Write-Host "Windows and Linux checksums and Pages metadata are ready."
