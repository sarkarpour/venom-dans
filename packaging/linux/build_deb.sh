#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build/deb_pkg"
DIST_DIR="${ROOT_DIR}/dist"
PKG_VERSION="0.1.0"
PKG_NAME="ferrowidget_${PKG_VERSION}_all"

echo "=== Building Debian/Ubuntu package: ${PKG_NAME}.deb ==="

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/ferrowidget"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${BUILD_DIR}/usr/lib/systemd/user"
mkdir -p "${DIST_DIR}"

# 1. DEBIAN/control
cat << 'EOF' > "${BUILD_DIR}/DEBIAN/control"
Package: ferrowidget
Version: 0.1.0
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pip, python3-venv, pulseaudio-utils, libxcb-cursor0, mesa-utils
Maintainer: FerroWidget Maintainers <asa@ferrowidget.local>
Description: Photorealistic ferrofluid desktop audio visualizer
 FerroWidget renders an obsidian, liquid ferrofluid floating directly on the
 desktop with a transparent background. It dances in real time to system audio
 with underdamped spring ODEs and studio HDR GLSL shaders.
EOF

# 2. DEBIAN/postinst
cat << 'EOF' > "${BUILD_DIR}/DEBIAN/postinst"
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
echo "FerroWidget installed successfully! Run 'ferrowidget run' or launch from application menu."
exit 0
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# 3. Copy application source
cp -r "${ROOT_DIR}/src/ferrowidget" "${BUILD_DIR}/usr/lib/ferrowidget/"
cp "${ROOT_DIR}/pyproject.toml" "${BUILD_DIR}/usr/lib/ferrowidget/"
find "${BUILD_DIR}/usr/lib/ferrowidget" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${BUILD_DIR}/usr/lib/ferrowidget" -name "*.pyc" -delete 2>/dev/null || true

# 4. Binary launcher wrapper
cat << 'EOF' > "${BUILD_DIR}/usr/bin/ferrowidget"
#!/usr/bin/env bash
set -e

# If user has virtualenv in ~/.local/share/ferrowidget/venv, use it, else system/user python
VENV_DIR="${HOME}/.local/share/ferrowidget/venv"
LIB_DIR="/usr/lib/ferrowidget"

if [ -f "${VENV_DIR}/bin/python3" ]; then
    exec "${VENV_DIR}/bin/python3" -m ferrowidget "$@"
elif python3 -c "import PySide6, moderngl, numpy" >/dev/null 2>&1; then
    export PYTHONPATH="${LIB_DIR}:${PYTHONPATH:-}"
    exec python3 -m ferrowidget "$@"
else
    echo "First time setup: Initializing FerroWidget Python environment..."
    mkdir -p "${HOME}/.local/share/ferrowidget"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --upgrade pip
    "${VENV_DIR}/bin/pip" install "${LIB_DIR}"
    exec "${VENV_DIR}/bin/python3" -m ferrowidget "$@"
fi
EOF
chmod 755 "${BUILD_DIR}/usr/bin/ferrowidget"

# 5. Desktop entry, service, icons
cp "${ROOT_DIR}/packaging/ferrowidget.desktop" "${BUILD_DIR}/usr/share/applications/"
cp "${ROOT_DIR}/packaging/ferrowidget.service" "${BUILD_DIR}/usr/lib/systemd/user/"
cp "${ROOT_DIR}/packaging/icons/ferrowidget.png" "${BUILD_DIR}/usr/share/icons/hicolor/256x256/apps/"
cp "${ROOT_DIR}/packaging/icons/ferrowidget.svg" "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps/"

# 6. Build .deb package
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DIST_DIR}/${PKG_NAME}.deb"
echo "Built package: ${DIST_DIR}/${PKG_NAME}.deb"
ls -lh "${DIST_DIR}/${PKG_NAME}.deb"
