#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${EUID} -ne 0 ]]; then
  exec sudo -- "$0" "$@"
fi

install -d /opt/mobile-base-imager /usr/local/bin /usr/share/applications /usr/share/icons/hicolor/256x256/apps
install -m 0755 "$HERE/mobile-base-imager" /opt/mobile-base-imager/mobile-base-imager
ln -sfn /opt/mobile-base-imager/mobile-base-imager /usr/local/bin/mobile-base-imager
install -m 0644 "$HERE/mobile-base-imager.desktop" /usr/share/applications/mobile-base-imager.desktop
install -m 0644 "$HERE/mobile-base-imager.png" /usr/share/icons/hicolor/256x256/apps/mobile-base-imager.png
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
echo "Mobile Base Imager installed. Launch it from the application menu or run: mobile-base-imager"
