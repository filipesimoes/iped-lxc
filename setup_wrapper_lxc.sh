#!/bin/bash
# setup_wrapper_lxc.sh
# Production deployment automation script for the IPED LXC Wrapper inside an LXC container.

set -euo pipefail

# Parse command line options
INSTALL_REDIS=true
for arg in "$@"; do
    case $arg in
        --skip-redis)
        INSTALL_REDIS=false
        shift
        ;;
    esac
done

# Ensure the script is run as root
if [ "${EUID}" -ne 0 ]; then
    echo "This script must be run as root (e.g. sudo ./setup_wrapper_lxc.sh)"
    exit 1
fi

echo "=========================================================="
echo " Starting IPED LXC Wrapper Production Deployment"
echo "=========================================================="

export DEBIAN_FRONTEND=noninteractive

# 1. Update OS packages and install core dependencies
if [ "$INSTALL_REDIS" = true ]; then
    echo "[1/7] Installing OS packages and Redis..."
    apt-get update
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        redis-server \
        git \
        curl \
        build-essential
else
    echo "[1/7] Installing OS packages (skipping local Redis)..."
    apt-get update
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        build-essential
fi

# 2. Configure Redis and Keyspace settings
API_KEY_VAL=$(python3 -c "import secrets; print(secrets.token_hex(16))")

if [ "$INSTALL_REDIS" = true ]; then
    echo "[2/7] Configuring local Redis keyspace notifications and security..."
    REDIS_CONF="/etc/redis/redis.conf"
    REDIS_PASS=$(python3 -c "import secrets; print(secrets.token_hex(16))")

    if [ -f "$REDIS_CONF" ]; then
        # Backup config
        cp "$REDIS_CONF" "${REDIS_CONF}.bak"
        # Ensure notify-keyspace-events is set to Ex
        if grep -q "^#\?\s*notify-keyspace-events" "$REDIS_CONF"; then
            sed -i 's/^\s*#\?\s*notify-keyspace-events.*/notify-keyspace-events "Ex"/' "$REDIS_CONF"
        else
            echo 'notify-keyspace-events "Ex"' >> "$REDIS_CONF"
        fi
        # Ensure bind is restricted to localhost (127.0.0.1)
        if grep -q "^#\?\s*bind" "$REDIS_CONF" | grep -qv "bind-address"; then
            sed -i 's/^\s*#\?\s*bind.*/bind 127.0.0.1 -::1/' "$REDIS_CONF"
        else
            echo 'bind 127.0.0.1 -::1' >> "$REDIS_CONF"
        fi
        # Ensure requirepass is set to the generated password
        if grep -q "^#\?\s*requirepass" "$REDIS_CONF"; then
            sed -i "s/^\s*#\?\s*requirepass.*/requirepass $REDIS_PASS/" "$REDIS_CONF"
        else
            echo "requirepass $REDIS_PASS" >> "$REDIS_CONF"
        fi
        echo "Restarting Redis service..."
        systemctl restart redis-server
        systemctl enable redis-server
    else
        echo "WARNING: /etc/redis/redis.conf not found. Ensure keyspace events (Ex) and requirepass are enabled manually."
    fi
else
    echo "[2/7] Skipping local Redis configuration (external Redis assumed)..."
    REDIS_PASS=""
fi

# 3. Create a dedicated system user
echo "[3/7] Creating system user 'ipedwrapper'..."
if ! id -u ipedwrapper >/dev/null 2>&1; then
    useradd -r -s /bin/false ipedwrapper
fi

# 4. Set up deployment directories
echo "[4/7] Setting up directories under /opt/iped-lxc-wrapper..."
INSTALL_DIR="/opt/iped-lxc-wrapper"
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/app"

# Copy files (assuming running script from the source directory)
cp -r app/* "$INSTALL_DIR/app/"
cp requirements.txt "$INSTALL_DIR/"

# Create a sample .env configuration file if it doesn't exist
ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating production environment configuration..."
    cat << EOF > "$ENV_FILE"
# ==========================================
# IPED LXC Wrapper Production Configuration
# ==========================================

# Security Configuration
API_KEY=$API_KEY_VAL
ALLOWED_ORIGINS=http://localhost,http://localhost:8000,http://localhost:3000

# Use False in production to orchestrate actual Proxmox LXC containers
MOCK_MODE=False
API_BASE_URL=http://your-wrapper-ip-or-domain.com

# Redis settings (pointing to local Redis server with generated credentials)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=$REDIS_PASS
SESSION_TTL=7200

# Proxmox API Settings
PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_USER=wrapper-api@pve
PROXMOX_VERIFY_SSL=True
# Authentication: Use API Token in production (highly recommended)
PROXMOX_TOKEN_NAME=wrapper-token
PROXMOX_TOKEN_VALUE=xxxx-xxxx-xxxx-xxxx
# Alternately use password (not recommended for production):
# PROXMOX_PASSWORD=somepassword

# Container allocation configurations

IPED_API_PORT=8080
EOF
    echo "Production .env file created at $ENV_FILE. Please configure Proxmox credentials."
fi

# 5. Create Virtual Environment and install packages
echo "[5/7] Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Ensure permissions
chown -R ipedwrapper:ipedwrapper "$INSTALL_DIR"
chmod 600 "$ENV_FILE"

# 6. Configure Systemd Services
echo "[6/7] Creating systemd service definitions..."

# FastAPI Web Service
cat << EOF > /etc/systemd/system/iped-wrapper-web.service
[Unit]
Description=IPED LXC Wrapper Web Service (FastAPI)
After=network.target redis-server.service

[Service]
User=ipedwrapper
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Celery Worker Service
cat << EOF > /etc/systemd/system/iped-wrapper-worker.service
[Unit]
Description=IPED LXC Wrapper Celery Worker
After=network.target redis-server.service

[Service]
User=ipedwrapper
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/celery -A app.celery_app worker --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 7. Reload systemd, enable and start services
echo "[7/7] Starting services..."
systemctl daemon-reload

systemctl enable iped-wrapper-web.service
systemctl enable iped-wrapper-worker.service

systemctl start iped-wrapper-web.service
systemctl start iped-wrapper-worker.service

echo "=========================================================="
echo " IPED LXC Wrapper Deployment Complete!"
echo " Web Service running on port 8000"
echo " Verify logs using:"
echo "   journalctl -u iped-wrapper-web.service -f"
echo "   journalctl -u iped-wrapper-worker.service -f"
echo "=========================================================="
