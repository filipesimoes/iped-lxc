import logging
import secrets
import time
import traceback
from typing import Optional
import httpx
from app.celery_app import celery_app
from app.config import settings
from app.proxmox_client import get_proxmox_client
from app.redis_state import set_job_status, set_session

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.provision_container_task", bind=True)
def provision_container_task(self, job_id: str, vmid: int, proxmox_node: str, proxmox_bridge: str, iped_api_key: str) -> str:
    logger.info(f"Starting provisioning for job {job_id}, VMID: {vmid} on node {proxmox_node} using bridge {proxmox_bridge}")
    set_job_status(job_id, "Starting", vmid=vmid)
    
    client = get_proxmox_client()
    node = proxmox_node
    
    try:
        # 1. Start Container
        logger.info(f"Starting container VMID: {vmid}...")
        client.start_container(node, vmid)
        
        # 2. Get IP Address
        lxc_ip = client.get_container_ip(node, vmid)
        set_job_status(job_id, "Starting", vmid=vmid, lxc_ip=lxc_ip)
        
        # 3. Poll IPED API until healthy (200 OK)
        # IPED API can take up to 2-3 minutes to start the Java/JVM process and load plugins
        iped_url = f"http://{lxc_ip}:{settings.IPED_API_PORT}"
        poll_timeout = 300  # 5 minutes
        poll_interval = 5
        start_poll = time.time()
        
        logger.info(f"Polling IPED API health at {iped_url}...")
        is_healthy = False
        
        # We will attempt to call /ping or /sources to check API availability
        while time.time() - start_poll < poll_timeout:
            try:
                # Use a short timeout for the check itself
                with httpx.Client(timeout=3.0) as http_client:
                    headers = {}
                    if iped_api_key:
                        headers["X-API-Key"] = iped_api_key
                    
                    # Query the /sources endpoint to check API availability
                    resp = http_client.get(f"{iped_url}/sources", headers=headers)
                        
                    if resp.status_code == 200:
                        logger.info("IPED API returned 200 OK. Container is healthy.")
                        is_healthy = True
                        break
            except (httpx.HTTPError, ConnectionError) as e:
                logger.debug(f"IPED API not ready yet: {e}")
                
            time.sleep(poll_interval)
            
        if not is_healthy:
            raise TimeoutError("IPED API did not become healthy within 5 minutes.")
            
        # 4. Create Session State and Token
        token = secrets.token_hex(16)
        
        metadata = {
            "vmid": vmid,
            "node": node,
            "lxc_ip": lxc_ip,
            "iped_api_key": iped_api_key,
            "data_path": None,
            "created_at": time.time()
        }
        
        # Save session to Redis
        set_session(token, metadata, settings.SESSION_TTL)
        
        # 5. Mark Job as Ready
        proxy_url = f"{settings.API_BASE_URL}/proxy/{token}"
        set_job_status(
            job_id, 
            "Ready", 
            token=token, 
            vmid=vmid, 
            lxc_ip=lxc_ip, 
            proxy_url=proxy_url
        )
        return token    
        
    except Exception as e:
        error_msg = (
            f"Failed to provision container for job '{job_id}' (VMID: {vmid}, "
            f"Node: '{node}')."
        )
        set_job_status(job_id, "Failed", error=error_msg)
        logger.error(error_msg)
        logger.error(f"Stacktrace: {traceback.format_exc()}")
        
        # Teardown the container to prevent resource leaks only if there are no other active sessions
        if vmid is not None:
            try:
                from app.redis_state import get_redis_client
                redis_client = get_redis_client()
                active_count = redis_client.scard(f"vmid_sessions:{vmid}")
                if active_count == 0:
                    logger.info(f"Teardown container VMID {vmid} as there are no active sessions.")
                    client.stop_container(node, vmid)
                else:
                    logger.info(
                        f"Failed provisioning for job {job_id}, but VMID {vmid} has {active_count} "
                        "active sessions. Leaving container running."
                    )
            except Exception as stop_err:
                logger.warning(f"Error checking/stopping failed container {vmid}: {stop_err}")
                
        raise e


@celery_app.task(name="app.tasks.destroy_container_task")
def destroy_container_task(vmid: int, node: str) -> None:
    logger.info(f"Stopping container VMID: {vmid} on node: {node}...")
    client = get_proxmox_client()
    
    try:
        client.stop_container(node, vmid)
        logger.info(f"Successfully stopped container {vmid}")
    except Exception as e:
        logger.error(f"Failed to stop container {vmid} during teardown: {e}")
        raise e
