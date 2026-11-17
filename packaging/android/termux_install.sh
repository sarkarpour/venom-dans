#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

echo "============================================="
echo "    FerroWidget Android (Termux) Installer   "
echo "============================================="

# 1. Update Termux repositories
pkg update -y
pkg install -y python x11-repo pulseaudio mesa termux-x11-nightly clang make libjpeg-turbo

# 2. Setup Virtual Environment
python -m venv ~/ferrowidget_env
source ~/ferrowidget_env/bin/activate
pip install --upgrade pip
pip install numpy moderngl tomli-w pillow
pip install "https://raw.githubusercontent.com/sarkarpour/venom-dans/main/dist/ferrowidget-0.1.0-py3-none-any.whl"

# 3. Create launch script
cat << 'EOF' > ~/start_ferrowidget.sh
#!/data/data/com.termux/files/usr/bin/bash
export DISPLAY=:0
pulseaudio --start --exit-idle-time=-1 || true
source ~/ferrowidget_env/bin/activate
python -m ferrowidget run --synthetic kick120
EOF
chmod +x ~/start_ferrowidget.sh

echo "============================================="
echo " Installation complete!                      "
echo " 1. Start Termux:X11 app                     "
echo " 2. Run: ~/start_ferrowidget.sh              "
echo "============================================="
