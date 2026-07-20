# Proxmox VE Integration & Container Configuration Guide

This guide describes how to configure Proxmox VE (PVE) and configure the IPED LXC containers to work with the **IPED LXC Wrapper**.

---

## 1. Proxmox VE API Token & Permissions

To bypass non-root restrictions in Proxmox when dealing with pre-configured templates or resource changes, the wrapper only requires minimal permissions (`VM.Audit` and `VM.PowerMgmt`) to manage the lifecycle of existing containers.

### CLI Quick Setup (Recommended)
Run these commands on the Proxmox host as `root` to configure the API user and token:

```bash
# 1. Create the Custom Role with lifecycle privileges
pveum role add LXCWrapper --privs "VM.Audit VM.PowerMgmt"

# 2. Create the system user (pve realm)
pveum user add wrapper-api@pve

# 3. Grant the role to the user
pveum acl modify / --roles LXCWrapper --users wrapper-api@pve

# 4. Create the API Token (with privilege separation)
pveum user token add wrapper-api@pve wrapper-token --privsep 1

# 5. Grant the role to the API Token
pveum acl modify / --roles LXCWrapper --tokens "wrapper-api@pve!wrapper-token"
```

Configure these credentials in your `.env` file:
```env
PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_USER=wrapper-api@pve
PROXMOX_TOKEN_NAME=wrapper-token
PROXMOX_TOKEN_VALUE=your-token-value-here
PROXMOX_VERIFY_SSL=True
```

---

## 2. Preparing the IPED LXC Container

The standard installation assumes the container is self-contained, with all forensic evidence and case data already present within the container's internal filesystem (e.g., under `/data`). No external network storage or CIFS mounting is required.

Make sure the configuration file `/data/iped/config.json` is correctly set up inside the container pointing to local source paths before running the API.

---

## 3. IPED Web API Service Setup

Bind the IPED Web API strictly to loopback (`127.0.0.1`) so it is only reachable via Nginx.

### Step 1: Startup Script (`/opt/IPED/iped/start-iped.sh`)
```bash
#!/bin/bash
set -e

CONFIG_FILE="/data/iped/config.json"
counter=0

while [ ! -f "$CONFIG_FILE" ] && [ $counter -lt 60 ]; do
    sleep 1
    counter=$((counter+1))
done

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found." >&2
    exit 1
fi

exec java -jar /opt/IPED/iped/iped-4.4.0-forked-1.1.0/lib/iped-webapi.jar --ip=127.0.0.1 --port=8080 --sources="file://${CONFIG_FILE}"
```
```bash
chmod +x /opt/IPED/iped/start-iped.sh
```

### Step 2: Systemd Service (`/etc/systemd/system/iped-api.service`)
```ini
[Unit]
Description=IPED REST API Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/IPED/iped
ExecStart=/opt/IPED/iped/start-iped.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now iped-api.service
```

---

## 4. Nginx Reverse Proxy with API Key Authentication

Configure Nginx inside the container to listen externally, authenticate requests with an `X-API-Key` header, and forward them to the IPED API on `127.0.0.1`.

### Step 1: Install Nginx
```bash
apt update && apt install nginx -y
```

### Step 2: Configure Reverse Proxy
Overwrite `/etc/nginx/sites-available/default`:
```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    server_name _;

    location / {
        if ($http_x_api_key != "SUA_CHAVE_SUPER_SEGURA") {
            return 403 "Acesso Negado: Chave de API invalida ou ausente.\n";
        }

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```
```bash
nginx -t && systemctl restart nginx
```

---

## 5. Aligning the IPED LXC Wrapper Configuration

1. In the wrapper's `.env` configuration file, configure the port:
   ```env
   IPED_API_PORT=80
   ```

2. **Provisioning Container Instance**:
   Start the pre-configured LXC container using the `/v1/instances/start` endpoint of the wrapper:
   ```http
   POST /v1/instances/start
   X-API-Key: wrapper-api-key-configured-in-env
   Content-Type: application/json

   {
     "vmid": 10000,
     "iped_api_key": "SUA_CHAVE_SUPER_SEGURA",
     "proxmox_node": "pve",
     "proxmox_bridge": "vmbr0"
   }
   ```

3. **Authentication Handshake**:
   * **Boot Verification**: The wrapper's background Celery task starts the container and obtains its IP. It then polls the container's `/sources` endpoint through Nginx (on port `80`) using the provided `iped_api_key` in the `X-API-Key` header.
   * **Proxy Handshake**: External clients authenticate against the wrapper using the wrapper's own `API_KEY`. The wrapper validates it, retrieves the session's specific `iped_api_key` from Redis, and automatically injects it as `X-API-Key` before forwarding the request to the container.
