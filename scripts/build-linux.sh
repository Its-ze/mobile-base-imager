#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?project root is required}"
VERSION="${2:-$(tr -d '\r\n' <"$ROOT/VERSION")}"
VENV="${MOBILE_BASE_IMAGER_LINUX_VENV:-/tmp/mobile-base-imager-venv}"
WORK="$(mktemp -d /tmp/mobile-base-imager-build.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/requirements-dev.txt"
cd "$ROOT"
"$VENV/bin/python" -m pytest -q

"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name mobile-base-imager \
  --add-data "$ROOT/assets/mobile-base-imager.png:assets" \
  --add-data "$ROOT/assets/mobile-base-imager.ico:assets" \
  --paths "$ROOT" \
  --distpath "$WORK/dist" \
  --workpath "$WORK/work" \
  --specpath "$WORK" \
  "$ROOT/app/mobile_base_imager.py"

DIST="$ROOT/dist"
mkdir -p "$DIST"
BINARY="$DIST/mobile-base-imager-v${VERSION}-linux-x86_64"
install -m 0755 "$WORK/dist/mobile-base-imager" "$BINARY"
"$BINARY" --self-test

PORTABLE="$WORK/portable/Mobile Base Imager"
mkdir -p "$PORTABLE"
install -m 0755 "$BINARY" "$PORTABLE/mobile-base-imager"
install -m 0755 "$ROOT/linux/install.sh" "$PORTABLE/install.sh"
install -m 0644 "$ROOT/linux/mobile-base-imager.desktop" "$PORTABLE/mobile-base-imager.desktop"
install -m 0644 "$ROOT/linux/README-LINUX.md" "$PORTABLE/README.md"
install -m 0644 "$ROOT/assets/mobile-base-imager.png" "$PORTABLE/mobile-base-imager.png"
install -m 0644 "$ROOT/LICENSE" "$PORTABLE/LICENSE"
TARBALL="$DIST/mobile-base-imager-v${VERSION}-linux-x86_64.tar.gz"
tar -C "$WORK/portable" -czf "$TARBALL" "Mobile Base Imager"

DEBROOT="$WORK/deb"
mkdir -p "$DEBROOT/DEBIAN" "$DEBROOT/opt/mobile-base-imager" "$DEBROOT/usr/bin" "$DEBROOT/usr/share/applications" "$DEBROOT/usr/share/icons/hicolor/256x256/apps"
sed "s/VERSION/$VERSION/g" "$ROOT/linux/debian-control" >"$DEBROOT/DEBIAN/control"
install -m 0755 "$BINARY" "$DEBROOT/opt/mobile-base-imager/mobile-base-imager"
ln -s /opt/mobile-base-imager/mobile-base-imager "$DEBROOT/usr/bin/mobile-base-imager"
install -m 0644 "$ROOT/linux/mobile-base-imager.desktop" "$DEBROOT/usr/share/applications/mobile-base-imager.desktop"
install -m 0644 "$ROOT/assets/mobile-base-imager.png" "$DEBROOT/usr/share/icons/hicolor/256x256/apps/mobile-base-imager.png"
DEB="$DIST/mobile-base-imager_${VERSION}_linux_amd64.deb"
dpkg-deb --build --root-owner-group "$DEBROOT" "$DEB" >/dev/null
INSTALLER="$DIST/install-mobile-base-imager.sh"
sed "s/@VERSION@/$VERSION/g" "$ROOT/linux/install-mobile-base-imager.sh" >"$INSTALLER"
chmod 0755 "$INSTALLER"

printf 'Linux release ready:\n  %s\n  %s\n  %s\n  %s\n' "$BINARY" "$TARBALL" "$DEB" "$INSTALLER"
