param(
  [string]$Owner = "Its-ze",
  [string]$Repo = "mobile-base-imager",
  [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim() }
Push-Location $Root
try {
  & gh auth status 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated. Run gh auth login first." }
  & (Join-Path $PSScriptRoot "build-release.ps1") -Version $Version
  if (-not (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
    & git init -b main
    & git config user.name "Zach Skeens"
    & git config user.email "zachskeens@users.noreply.github.com"
  }
  & git add .github .gitignore LICENSE README.md VERSION app assets docs requirements.txt requirements-dev.txt scripts tests
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
  $releaseTag = & gh release list --repo "$Owner/$Repo" --limit 100 --json tagName --jq ".[] | select(.tagName == \"$tag\") | .tagName"
  if ($releaseTag -ne $tag) {
    & gh release create $tag --repo "$Owner/$Repo" --title "Mobile Base Imager $tag" --notes "Complete Windows imaging workspace with safe removable-drive filtering, five image formats, verified downloads, raw flashing, full readback, verify-only comparison, compressed backups, formatting, checksums, cache tools, and operation logs."
    if ($LASTEXITCODE -ne 0) { throw "Could not create the GitHub release." }
  }
  $assets = @(
    "dist\mobile-base-imager-v$Version-windows-x64.exe",
    "dist\mobile-base-imager-v$Version-windows-x64.zip",
    "dist\mobile-base-pi5-0.8.0.img.zst",
    "dist\mobile-base-pi5-0.8.0.img.zst.sha256",
    "dist\checksums.txt"
  )
  & gh release upload $tag @assets --repo "$Owner/$Repo" --clobber
  if ($LASTEXITCODE -ne 0) { throw "Could not upload one or more release assets." }
  Write-Host "Repository: https://github.com/$Owner/$Repo"
  Write-Host "Download page: https://$($Owner.ToLowerInvariant()).github.io/$Repo/"
  Write-Host "Release: https://github.com/$Owner/$Repo/releases/tag/$tag"
} finally {
  Pop-Location
}
