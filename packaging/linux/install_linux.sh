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

# Detect execution context (git clone, standalone bundle, or curl pipe)
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

ROOT_DIR=""
if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/../../pyproject.toml" ]; then
    ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
elif [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/pyproject.toml" ]; then
    ROOT_DIR="${SCRIPT_DIR}"
fi

WHEEL_FILE=""
if [ -n "${SCRIPT_DIR}" ]; then
    for w in "${SCRIPT_DIR}"/ferrowidget-*.whl; do
        if [ -f "$w" ]; then
            WHEEL_FILE="$w"
            break
        fi
    done
fi

RAW_BASE="https://raw.githubusercontent.com/sarkarpour/venom-dans/main"

echo "1. Checking Python 3 and virtual environment..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Please install Python 3.10+ first."
    exit 1
fi

if [ ! -d "${INSTALL_DIR}/venv" ]; then
    python3 -m venv "${INSTALL_DIR}/venv" || {
        echo "[ERROR] Failed to create virtual environment. Please install python3-venv (e.g. sudo apt install python3-venv)."
        exit 1
    }
fi

echo "2. Installing package dependencies..."
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip

if [ -n "${WHEEL_FILE}" ]; then
    echo "Installing from local wheel: ${WHEEL_FILE}..."
    "${INSTALL_DIR}/venv/bin/pip" install "${WHEEL_FILE}"
elif [ -n "${ROOT_DIR}" ]; then
    echo "Installing from local source: ${ROOT_DIR}..."
    "${INSTALL_DIR}/venv/bin/pip" install -e "${ROOT_DIR}"
else
    echo "Installing latest package from repository CDN..."
    "${INSTALL_DIR}/venv/bin/pip" install "${RAW_BASE}/dist/ferrowidget-0.1.0-py3-none-any.whl"
fi

echo "3. Creating CLI launcher in ${BIN_DIR}/ferrowidget..."
cat << EOF > "${BIN_DIR}/ferrowidget"
#!/usr/bin/env bash
exec "${INSTALL_DIR}/venv/bin/python3" -m ferrowidget "\$@"
EOF
chmod +x "${BIN_DIR}/ferrowidget"

echo "4. Installing desktop icon and application launcher..."
if [ -n "${ROOT_DIR}" ] && [ -f "${ROOT_DIR}/packaging/icons/ferrowidget.png" ]; then
    cp "${ROOT_DIR}/packaging/icons/ferrowidget.png" "${ICON_DIR}/ferrowidget.png"
elif [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/ferrowidget.png" ]; then
    cp "${SCRIPT_DIR}/ferrowidget.png" "${ICON_DIR}/ferrowidget.png"
else
    curl -sSL "${RAW_BASE}/packaging/icons/ferrowidget.png" -o "${ICON_DIR}/ferrowidget.png" || true
fi

cat << EOF > "${DESKTOP_DIR}/ferrowidget.desktop"
[Desktop Entry]
Name=FerroWidget
GenericName=Ferrofluid Audio Visualizer
Comment=Photorealistic dancing ferrofluid desktop widget
Exec=${BIN_DIR}/ferrowidget run
Icon=${ICON_DIR}/ferrowidget.png
Terminal=false
Type=Application
Categories=AudioVideo;Utility;
StartupNotify=false
EOF
chmod +x "${DESKTOP_DIR}/ferrowidget.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" || true
fi

echo "============================================="
echo " FerroWidget installation complete!          "
echo " Run with: ferrowidget run                   "
echo " Or find 'FerroWidget' in your app menu.     "
echo "============================================="
