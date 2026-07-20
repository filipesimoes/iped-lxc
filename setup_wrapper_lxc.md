# IPED LXC Wrapper Deployment Guide (LXC Container)

This guide describes how to deploy the **IPED LXC Wrapper API service** (FastAPI Web API, Redis, and Celery Worker) inside a dedicated LXC container in Proxmox VE.

---

## 1. Container Requirements

Create a new LXC container in Proxmox to host the wrapper API with the following recommended settings:

* **OS Template**: Debian 12 or Ubuntu 22.04 / 24.04 LTS (Standard Linux container).
* **Unprivileged**: Yes (it does not require privileged mounting because it only calls the Proxmox API and manages local state).
* **Resources**: 
  * **CPU**: 1 to 2 vCPUs
  * **RAM**: 1 GB to 2 GB
  * **Disk**: 10 GB (mostly for logs and Redis state databases)
* **Network**: Static or DHCP IP, with connectivity to the Proxmox VE cluster API port (usually `8006` or `443`).

---

## 2. Automated Deployment (Recommended)

The project includes an automation script (`setup_wrapper_lxc.sh`) that installs dependencies, configures Redis security, sets up a virtual environment, installs Systemd services, and secures access.

### Step 1: Copy Project Files to the Container
Copy the project folder to the container or clone it inside the container under a temporary folder.

### Step 2: Execute the Setup Script
Run the script as `root` (optionally using the `--skip-redis` flag if using an external Redis instance):

```bash
chmod +x setup_wrapper_lxc.sh

# To deploy with a local Redis server automatically configured:
sudo ./setup_wrapper_lxc.sh

# To deploy using an external Redis (skips local Redis installation/configuration):
sudo ./setup_wrapper_lxc.sh --skip-redis
```

The script will automatically:
1. Update apt packages and install `python3`, dependencies, and optionally `redis-server`.
2. Configure local Redis security and Keyspace events (if local Redis is not skipped).
3. Set up the installation directory `/opt/iped-lxc-wrapper` with a dedicated system user `ipedwrapper`.
4. Create a production virtual environment and install packages from `requirements.txt`.
5. Create and start two Systemd services:
   * `iped-wrapper-web.service` (FastAPI at port `8000`)
   * `iped-wrapper-worker.service` (Celery background worker)

### Step 3: Configure the Environment Variables
Edit the generated environment configuration file `/opt/iped-lxc-wrapper/.env`:
```bash
sudo nano /opt/iped-lxc-wrapper/.env
```

Set the following parameters to match your Proxmox installation:
```env
# Use False in production to orchestrate actual Proxmox LXC containers
MOCK_MODE=False

# API Base URL (IP or domain of the wrapper container)
API_BASE_URL=http://<WRAPPER_LXC_IP>:8000

# Proxmox VE connection configuration
PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_USER=wrapper-api@pve
PROXMOX_TOKEN_NAME=wrapper-token
PROXMOX_TOKEN_VALUE=your-token-uuid-here
PROXMOX_VERIFY_SSL=True
```

### Step 4: Restart Services
Restart the services to load the updated environment variables:
```bash
sudo systemctl restart iped-wrapper-web.service
sudo systemctl restart iped-wrapper-worker.service
```

---

## 3. Manual Deployment (Step-by-Step)

If you prefer to configure the deployment manually, follow these steps:

### Step 1: Install OS Dependencies
Install basic dependencies (include `redis-server` only if you want to deploy Redis locally on this container):
```bash
sudo apt update
# With local Redis:
sudo apt install -y python3 python3-pip python3-venv redis-server git build-essential

# Without local Redis (external Redis):
sudo apt install -y python3 python3-pip python3-venv git build-essential
```

### Step 2: Configure Redis (Skip if using external Redis)
If running Redis locally, open `/etc/redis/redis.conf` and ensure the following security settings and keyspace event notifications are set:
```ini
bind 127.0.0.1 -::1
requirepass YOUR_STRONG_REDIS_PASSWORD
notify-keyspace-events "Ex"
```
Restart local Redis:
```bash
sudo systemctl restart redis-server
```

### Step 3: Setup Directory and Virtual Environment
```bash
sudo mkdir -p /opt/iped-lxc-wrapper
sudo cp -r app requirements.txt /opt/iped-lxc-wrapper/

# Create venv and install requirements
sudo python3 -m venv /opt/iped-lxc-wrapper/venv
sudo /opt/iped-lxc-wrapper/venv/bin/pip install --upgrade pip
sudo /opt/iped-lxc-wrapper/venv/bin/pip install -r /opt/iped-lxc-wrapper/requirements.txt
```

### Step 4: Add System User & Set Permissions
```bash
sudo useradd -r -s /bin/false ipedwrapper
sudo chown -R ipedwrapper:ipedwrapper /opt/iped-lxc-wrapper
```

### Step 5: Configure `.env` File
Create `/opt/iped-lxc-wrapper/.env`:
```env
API_KEY=your_client_api_auth_key
MOCK_MODE=False
API_BASE_URL=http://<WRAPPER_CONTAINER_IP>:8000

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=YOUR_STRONG_REDIS_PASSWORD
SESSION_TTL=7200

PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_USER=wrapper-api@pve
PROXMOX_TOKEN_NAME=wrapper-token
PROXMOX_TOKEN_VALUE=your-token-uuid-here
PROXMOX_VERIFY_SSL=True

IPED_API_PORT=80
```
Secure the `.env` file:
```bash
sudo chmod 600 /opt/iped-lxc-wrapper/.env
sudo chown ipedwrapper:ipedwrapper /opt/iped-lxc-wrapper/.env
```

### Step 6: Create Systemd Services

1. **FastAPI Web Service**: Create `/etc/systemd/system/iped-wrapper-web.service`:
   ```ini
   [Unit]
   Description=IPED LXC Wrapper Web Service (FastAPI)
   After=network.target redis-server.service

   [Service]
   User=ipedwrapper
   WorkingDirectory=/opt/iped-lxc-wrapper
   EnvironmentFile=/opt/iped-lxc-wrapper/.env
   ExecStart=/opt/iped-lxc-wrapper/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

2. **Celery Worker Service**: Create `/etc/systemd/system/iped-wrapper-worker.service`:
   ```ini
   [Unit]
   Description=IPED LXC Wrapper Celery Worker
   After=network.target redis-server.service

   [Service]
   User=ipedwrapper
   WorkingDirectory=/opt/iped-lxc-wrapper
   EnvironmentFile=/opt/iped-lxc-wrapper/.env
   ExecStart=/opt/iped-lxc-wrapper/venv/bin/celery -A app.celery_app worker --loglevel=info
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

### Step 7: Load and Start Services
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now iped-wrapper-web.service iped-wrapper-worker.service
```

---

## 4. Verification and Troubleshooting

### Check Service Status
```bash
sudo systemctl status iped-wrapper-web.service
sudo systemctl status iped-wrapper-worker.service
```

### Stream Live Logs
```bash
journalctl -u iped-wrapper-web.service -f
journalctl -u iped-wrapper-worker.service -f
```

### Test API Response
Verify the health check endpoint using curl:
```bash
curl -i http://localhost:8000/ping
```
*(This endpoint will return HTTP 401 if you do not provide the correct `X-API-Key` configured in `.env`)*

To call with the configured `API_KEY`:
```bash
curl -i -H "X-API-Key: your_client_api_auth_key" http://localhost:8000/ping
```
Expected output:
```json
{"ping": "pong", "mock_mode": false}
```
