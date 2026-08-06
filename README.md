# IPED LXC Wrapper

A lightweight API wrapper built with **FastAPI**, **Celery**, and **Redis** for on-demand orchestration and transparent reverse proxy routing of [**IPED**](https://github.com/sepinf-inc/IPED) (*Indexador e Processador de Evidências Digitais* / Digital Evidence Indexer and Processor) instances running in Linux Containers (LXC) on **Proxmox VE (PVE)**.

---

## 📌 Overview

The **IPED LXC Wrapper** simplifies and automates the lifecycle management of [IPED](https://github.com/sepinf-inc/IPED) digital forensic processing environments virtualized in Proxmox VE. 

Via a unified REST API, external client systems can provision IPED LXC containers on demand, track container startup status, and interact seamlessly with the internal IPED Web API via a transparent reverse proxy—all while leveraging automatic session inactivity timeouts (TTL) to automatically shut down containers when no longer in use, saving server compute resources.

---

## ✨ Features

- **On-Demand Orchestration (`/v1/instances`)**: Spawns pre-configured LXC containers in Proxmox VE, waits for network IP acquisition, and validates service readiness.
- **Transparent Reverse Proxy Routing (`/proxy/{session_id}/{path}`)**: Dynamically routes incoming HTTP requests to the target container's IPED Web API, automatically injecting container-specific authentication credentials (`X-API-Key`).
- **Automatic Session & TTL Management**: Enforces inactivity timeouts (e.g., 2 hours) using Redis Keyspace Expiration events (`notify-keyspace-events "Ex"`) to automatically terminate idle LXC containers.
- **Development & Testing Mode (`MOCK_MODE`)**: Built-in mock engine that allows local development and unit testing without requiring a live Proxmox VE cluster.
- **Asynchronous Task Processing**: Powered by Celery workers to handle background container boot polling, health verifications, and graceful container shutdowns.
- **Authentication & Security**: Protects wrapper endpoints via configurable `X-API-Key` headers and isolates public API keys from internal container credentials.

---

## 📚 Project Documentation

Detailed technical deployment and configuration guides are available in the following repository files:

| Document | Description |
| :--- | :--- |
| 📖 [**Proxmox VE & IPED Container Setup Guide**](setup_proxmox.md) | Step-by-step instructions for Proxmox VE API role/token configuration (`VM.Audit`, `VM.PowerMgmt`), systemd IPED Web API service setup, and Nginx reverse proxy configuration inside LXC containers. |
| 🚀 [**IPED LXC Wrapper Deployment Guide**](setup_wrapper_lxc.md) | Complete guide for deploying the Wrapper API service (FastAPI, Redis, Celery Worker) inside a dedicated LXC container, including automated and manual setup options. |

### 🛠️ Automation Scripts & Configuration

- ⚙️ [`setup_wrapper_lxc.sh`](setup_wrapper_lxc.sh): Shell script for automated installation of OS packages, Redis security tuning, Python venv creation, and Systemd service installation.
- 🔄 [`update_wrapper_lxc.sh`](update_wrapper_lxc.sh): Automation script to pull the latest code updates via Git, update Python dependencies, fix permissions, and restart services.
- 📋 [`.env.example`](.env.example): Environment variable template file containing all configuration keys.

---

## 🏗️ System Architecture

```
                         +-----------------------+
                         |       API Client      |
                         +-----------+-----------+
                                     | (X-API-Key)
                                     v
                         +-----------+-----------+
                         |  IPED LXC Wrapper API |
                         |    (FastAPI / 8000)   |
                         +-----+-----------+-----+
                               |           |
            +------------------+           +------------------+
            | Async Tasks                                     | Proxy Request
            v                                                 v
  +---------+---------+                             +---------+---------+
  |   Celery Worker   |                             |   Redis Storage   |
  | (Boot verification|                             | (Sessions & TTL)  |
  +---------+---------+                             +---------+---------+
            |                                                 | (Expired Event)
            | REST API (Token)                                v
            v                                       +---------+---------+
  +---------+---------+                             | Expired Listener  |
  |    Proxmox VE     |                             +---------+---------+
  |  (Start/Stop LXC) |                                       |
  +---------+---------+                                       | Stop LXC
            |                                                 v
            +-----------------------+-------------------------+
                                    |
                                    v
                        +-----------+-----------+
                        |   LXC IPED Container  |
                        | Nginx (80) -> IPED(8080)|
                        +-----------------------+
```

---

## 🚀 Getting Started

### 1. Environment Configuration

Create a `.env` file from the provided `.env.example` template:

```bash
cp .env.example .env
```

Configure the environment variables according to your deployment target:

```env
# Client authentication key for accessing the Wrapper API
API_KEY=your-secure-wrapper-api-key

# Set to True for local development/testing; False for production Proxmox integration
MOCK_MODE=True

# Proxmox VE API Configuration (required when MOCK_MODE=False)
PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_USER=wrapper-api@pve
PROXMOX_TOKEN_NAME=wrapper-token
PROXMOX_TOKEN_VALUE=your-token-uuid-value

# Redis Storage Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
SESSION_TTL=7200
```

### 2. Local Execution with Docker Compose

To launch the development stack (FastAPI App + Redis) locally using Docker Compose:

```bash
docker-compose up -d --build
```

Access interactive API documentation in your browser:
- **Swagger UI**: `http://localhost:8001/docs`
- **ReDoc**: `http://localhost:8001/redoc`

### 3. Production Deployment in LXC

To deploy the Wrapper on a dedicated LXC container in Proxmox VE, refer to the [**IPED LXC Wrapper Deployment Guide**](setup_wrapper_lxc.md) or execute the automated setup script:

```bash
chmod +x setup_wrapper_lxc.sh
sudo ./setup_wrapper_lxc.sh
```

---

## 🔗 API Endpoint Overview

### 🟢 Health Check
- `GET /ping`: Returns service operational status and active `mock_mode` state.

### 📦 Instance Orchestration (`/v1/instances`)
- `POST /v1/instances/start`: Triggers LXC container start in Proxmox and registers session state in Redis.
- `GET /v1/instances/status/{session_id}`: Polls container boot verification and IPED API readiness status.
- `POST /v1/instances/stop/{session_id}`: Manually terminates a session and requests container shutdown in Proxmox.

### 🔄 Reverse Proxy Routing (`/proxy`)
- `ALL /proxy/{session_id}/{path}`: Transparently forwards incoming HTTP requests to the IPED API instance running inside the LXC container assigned to `session_id`.

---

## 📑 Documentation Index

- 📄 [README.md](README.md)
- 📖 [setup_proxmox.md](setup_proxmox.md)
- 🚀 [setup_wrapper_lxc.md](setup_wrapper_lxc.md)
- ⚙️ [setup_wrapper_lxc.sh](setup_wrapper_lxc.sh)
- 🔄 [update_wrapper_lxc.sh](update_wrapper_lxc.sh)
- 📋 [.env.example](.env.example)
