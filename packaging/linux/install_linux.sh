#!/usr/bin/env bash
set -euo pipefail

echo "============================================="
echo "       FerroWidget Linux Installer          "
echo "============================================="

INSTALL_DIR="${HOME}/.local/share/ferrowidget"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"

mkdir -p "${INSTALL_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}" "${ICON_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "1. Installing Python virtual environment in ${INSTALL_DIR}/venv..."
if [ ! -d "${INSTALL_DIR}/venv" ]; then
    python3 -m venv "${INSTALL_DIR}/venv"
fi

echo "2. Installing package dependencies..."
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install -e "${ROOT_DIR}"

echo "3. Creating CLI launcher in ${BIN_DIR}/ferrowidget..."
cat << EOF > "${BIN_DIR}/ferrowidget"
#!/usr/bin/env bash
exec "${INSTALL_DIR}/venv/bin/python3" -m ferrowidget "\$@"
EOF
chmod +x "${BIN_DIR}/ferrowidget"

echo "4. Installing desktop icon and launcher..."
cp "${ROOT_DIR}/packaging/icons/ferrowidget.png" "${ICON_DIR}/ferrowidget.png"
sed -e "s|Exec=ferrowidget run|Exec=${BIN_DIR}/ferrowidget run|" \
    -e "s|Icon=ferrowidget|Icon=${ICON_DIR}/ferrowidget.png|" \
    "${ROOT_DIR}/packaging/ferrowidget.desktop" > "${DESKTOP_DIR}/ferrowidget.desktop"
chmod +x "${DESKTOP_DIR}/ferrowidget.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" || true
fi

echo "============================================="
echo " FerroWidget installation complete!          "
echo " Run with: ferrowidget run                   "
echo " Or find 'FerroWidget' in your app menu.     "
echo "============================================="
