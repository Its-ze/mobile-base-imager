param(
  [string]$Owner = "Its-ze",
  [string]$Repo = "mobile-base-imager",
  [string]$Version = "",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim() }
$PreviousGhToken = [Environment]::GetEnvironmentVariable("GH_TOKEN", "Process")
if ([string]::IsNullOrWhiteSpace($PreviousGhToken)) {
  $TokenFile = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN_FILE", "Process")
  if (-not [string]::IsNullOrWhiteSpace($TokenFile) -and (Test-Path -LiteralPath $TokenFile)) {
    $StoredToken = Import-Clixml -LiteralPath $TokenFile
    if ($StoredToken -isnot [securestring]) { throw "GITHUB_TOKEN_FILE must contain an encrypted SecureString." }
    $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($StoredToken)
    try {
      [Environment]::SetEnvironmentVariable(
        "GH_TOKEN",
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr),
        "Process"
      )
    } finally {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
    }
  }
}
Push-Location $Root
try {
  & gh auth status 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated. Run gh auth login first." }
  if ($SkipBuild) {
    & (Join-Path $PSScriptRoot "build-linux.ps1") -Version $Version -SkipCompile
  } else {
    & (Join-Path $PSScriptRoot "build-release.ps1") -Version $Version
    & (Join-Path $PSScriptRoot "build-linux.ps1") -Version $Version
  }
  if (-not (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
    & git init -b main
    & git config user.name "Zach Skeens"
    & git config user.email "zachskeens@users.noreply.github.com"
  }
  & git add .github .gitattributes .gitignore LICENSE README.md VERSION app assets docs linux requirements.txt requirements-dev.txt scripts tests
  if ($LASTEXITCODE -ne 0) { throw "Could not stage Mobile Base Imager files." }
  & git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    & git commit -m "Build Mobile Base Imager $Version"
    if ($LASTEXITCODE -ne 0) { throw "Could not commit the release." }
  }
  $remotes = @(& git remote)
  if ($remotes -notcontains "origin") {
    & gh repo create "$Owner/$Repo" --public --source . --remote origin --description "Safe Windows SD card formatter and flasher for the Mobile Base Raspberry Pi appliance"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the GitHub repository." }
  }
  & git push -u origin main
  if ($LASTEXITCODE -ne 0) { throw "Could not push main to GitHub." }
  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & gh api "repos/$Owner/$Repo/pages" -X POST -f build_type=workflow 2>$null | Out-Null
  $pagesCreateExit = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorAction
  if ($pagesCreateExit -ne 0) {
    & gh api "repos/$Owner/$Repo/pages" -X PUT -f build_type=workflow | Out-Null
  }
  $tag = "v$Version"
  $releaseTags = @((& gh release list --repo "$Owner/$Repo" --limit 100 --json tagName | ConvertFrom-Json) | ForEach-Object { $_.tagName })
  if ($releaseTags -notcontains $tag) {
    $releaseNotes = @"
Mobile Base Imager $tag publishes the verified Mobile Base 0.9.4 appliance image for Raspberry Pi 5.

Mobile Base 0.9.4 adds plug-and-play USB NMEA GPS detection, supervised gpsd worker startup, automatic mission creation or resume, Raspberry Pi 5 Bluetooth firmware, and reboot-persistent local BLE discovery/status/control. Provisioned units retain key-only `mobileadmin` access, single-use outbound Hub enrollment, and no embedded private credential in the public image.

The imager retains safe removable-drive filtering, verified downloads, raw flashing, full readback, verify-only comparison, compressed backups, formatting, checksums, cache tools, and operation logs.
"@
    & gh release create $tag --repo "$Owner/$Repo" --title "Mobile Base Imager $tag" --notes $releaseNotes
    if ($LASTEXITCODE -ne 0) { throw "Could not create the GitHub release." }
  }
  $assets = @(
    "dist\mobile-base-imager-v$Version-windows-x64.exe",
    "dist\mobile-base-imager-v$Version-windows-x64.zip",
    "dist\mobile-base-imager-v$Version-linux-x86_64",
    "dist\mobile-base-imager-v$Version-linux-x86_64.tar.gz",
    "dist\mobile-base-imager_$($Version)_linux_amd64.deb",
    "dist\Mobile_Base_Imager-$Version-x86_64.AppImage",
    "dist\install-mobile-base-imager.sh",
    "dist\mobile-base-pi5-0.9.4.img.zst",
    "dist\mobile-base-pi5-0.9.4.img.zst.sha256",
    "dist\checksums.txt"
  )
  & gh release upload $tag @assets --repo "$Owner/$Repo" --clobber
  if ($LASTEXITCODE -ne 0) { throw "Could not upload one or more release assets." }
  Write-Host "Repository: https://github.com/$Owner/$Repo"
  Write-Host "Download page: https://$($Owner.ToLowerInvariant()).github.io/$Repo/"
  Write-Host "Release: https://github.com/$Owner/$Repo/releases/tag/$tag"
} finally {
  [Environment]::SetEnvironmentVariable("GH_TOKEN", $PreviousGhToken, "Process")
  Pop-Location
}
