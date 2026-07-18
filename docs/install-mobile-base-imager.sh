#!/usr/bin/env bash
set -euo pipefail

PRODUCT="Mobile Base Imager"
VERSION="${MOBILE_BASE_IMAGER_VERSION:-0.3.6}"
REPOSITORY="${MOBILE_BASE_IMAGER_REPOSITORY:-Its-ze/mobile-base-imager}"
RELEASE_BASE="${MOBILE_BASE_IMAGER_RELEASE_BASE_URL:-https://github.com/${REPOSITORY}/releases/download/v${VERSION}}"
DEB_NAME="mobile-base-imager_${VERSION}_linux_amd64.deb"

usage() {
  cat <<EOF
Install ${PRODUCT} ${VERSION} on Debian or Ubuntu x86_64.

Usage: bash install-mobile-base-imager.sh

Environment overrides:
  MOBILE_BASE_IMAGER_VERSION           Release version to install
  MOBILE_BASE_IMAGER_REPOSITORY        GitHub owner/repository
  MOBILE_BASE_IMAGER_RELEASE_BASE_URL  Alternate release asset base URL
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    echo "${PRODUCT} currently supports Linux x86_64/amd64 only." >&2
    exit 1
    ;;
esac

if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg >/dev/null 2>&1; then
  echo "This installer requires a Debian or Ubuntu system with APT." >&2
  exit 1
fi

if [[ ${EUID} -eq 0 ]]; then
  AS_ROOT=()
elif command -v sudo >/dev/null 2>&1; then
  AS_ROOT=(sudo)
  "${AS_ROOT[@]}" -v
else
  echo "Run this installer as root or install sudo." >&2
  exit 1
fi

download() {
  local url="$1"
  local destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --show-error --silent "$url" --output "$destination"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --tries=3 --output-document="$destination" "$url"
  else
    echo "Installing the download helper..."
    "${AS_ROOT[@]}" apt-get update
    "${AS_ROOT[@]}" apt-get install -y curl ca-certificates
    curl --fail --location --retry 3 --show-error --silent "$url" --output "$destination"
  fi
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mobile-base-imager-install.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
DEB_PATH="$WORK/$DEB_NAME"
CHECKSUMS="$WORK/checksums.txt"

echo "Downloading ${PRODUCT} ${VERSION}..."
download "$RELEASE_BASE/$DEB_NAME" "$DEB_PATH"
download "$RELEASE_BASE/checksums.txt" "$CHECKSUMS"

expected="$(awk -v name="$DEB_NAME" '$2 == name {print tolower($1); exit}' "$CHECKSUMS")"
if [[ ! $expected =~ ^[0-9a-f]{64}$ ]]; then
  echo "The release checksum for $DEB_NAME is missing or invalid." >&2
  exit 1
fi
actual="$(sha256sum "$DEB_PATH" | awk '{print tolower($1)}')"
if [[ $actual != "$expected" ]]; then
  echo "Checksum verification failed. The package will not be installed." >&2
  exit 1
fi
echo "SHA-256 verified."

echo "Installing ${PRODUCT} and required system packages..."
if ! "${AS_ROOT[@]}" apt-get install -y "$DEB_PATH"; then
  echo "Refreshing APT package metadata and retrying..."
  "${AS_ROOT[@]}" apt-get update
  "${AS_ROOT[@]}" apt-get install -y "$DEB_PATH"
fi

/usr/bin/mobile-base-imager --self-test >/dev/null
echo "${PRODUCT} ${VERSION} installed successfully."
echo "Launch it from your application menu or run: mobile-base-imager"
