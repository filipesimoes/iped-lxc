#!/bin/bash
# update_wrapper_lxc.sh
# Update automation script for the IPED LXC Wrapper inside an LXC container.

set -euo pipefail

# Ensure the script is run as root
if [ "${EUID}" -ne 0 ]; then
    echo "This script must be run as root (e.g. sudo ./update_wrapper_lxc.sh)"
    exit 1
fi

echo "=========================================================="
echo " Updating IPED LXC Wrapper Services"
echo "=========================================================="

INSTALL_DIR="/opt/iped-lxc-wrapper"

if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "ERROR: $INSTALL_DIR is not a git repository."
    echo "This update script requires the wrapper to be deployed via git clone."
    exit 1
fi

# 1. Pull latest code
echo "[1/4] Pulling latest changes from repository..."
# Add to safe.directory to prevent dubious ownership issues
git config --global --add safe.directory "$INSTALL_DIR" || true

cd "$INSTALL_DIR"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Detected current branch: $CURRENT_BRANCH"

git fetch origin "$CURRENT_BRANCH"
git reset --hard "origin/$CURRENT_BRANCH"

# 2. Update Python dependencies
echo "[2/4] Updating Python virtual environment packages..."
if [ -d "$INSTALL_DIR/venv" ]; then
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
else
    echo "Virtual environment not found. Setting it up..."
    python3 -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
fi

# 3. Ensure proper file permissions
echo "[3/4] Securing file permissions..."
chown -R ipedwrapper:ipedwrapper "$INSTALL_DIR"
if [ -f "$INSTALL_DIR/.env" ]; then
    chmod 600 "$INSTALL_DIR/.env"
fi

# 4. Restart Services
echo "[4/4] Restarting systemd services..."
systemctl daemon-reload
systemctl restart iped-wrapper-web.service
systemctl restart iped-wrapper-worker.service

echo "Checking service status..."
sleep 2

WEB_STATUS=$(systemctl is-active iped-wrapper-web.service || echo "failed")
WORKER_STATUS=$(systemctl is-active iped-wrapper-worker.service || echo "failed")

echo "=========================================================="
echo " Update Complete!"
echo " Web Service status:    $WEB_STATUS"
echo " Worker Service status: $WORKER_STATUS"
echo "=========================================================="
