import json
import logging
import threading
import time
from typing import Any, Dict, Optional
import redis
from app.config import settings

logger = logging.getLogger(__name__)

# Single redis client instance
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )
    return _redis_client


# Session Management (Shadow Key Pattern)
# We store:
# 1. session_ttl:{token} -> value "1", with EXPIRE set to settings.SESSION_TTL
# 2. session:{token} -> JSON containing metadata (vmid, node, ip, data_path), no TTL (or long TTL)

def set_session(token: str, metadata: Dict[str, Any], ttl: int = settings.SESSION_TTL) -> None:
    client = get_redis_client()
    shadow_key = f"session:{token}"
    ttl_key = f"session_ttl:{token}"
    
    # Store metadata
    client.set(shadow_key, json.dumps(metadata))
    # Store TTL trigger key
    client.set(ttl_key, "1", ex=ttl)
    
    # Register token in the active sessions set for the VMID
    vmid = metadata.get("vmid")
    if vmid:
        client.sadd(f"vmid_sessions:{vmid}", token)
        
    logger.info(f"Session saved for token: {token} with TTL: {ttl}s. Added to VMID {vmid} active sessions.")


def get_session(token: str) -> Optional[Dict[str, Any]]:
    client = get_redis_client()
    ttl_key = f"session_ttl:{token}"
    shadow_key = f"session:{token}"
    
    # Verify if TTL key exists (if not, it has expired)
    if not client.exists(ttl_key):
        return None
        
    data = client.get(shadow_key)
    if data:
        return json.loads(data)
    return None


def refresh_session(token: str, ttl: int = settings.SESSION_TTL) -> None:
    client = get_redis_client()
    ttl_key = f"session_ttl:{token}"
    if client.exists(ttl_key):
        client.expire(ttl_key, ttl)
        logger.debug(f"Refreshed session TTL for token: {token} to {ttl}s")


def delete_session(token: str) -> bool:
    """
    Deletes the session and returns True if this was the last active session
    for the associated VMID, False otherwise.
    """
    client = get_redis_client()
    shadow_key = f"session:{token}"
    data_str = client.get(shadow_key)
    
    is_last = True
    vmid = None
    if data_str:
        try:
            metadata = json.loads(data_str)
            vmid = metadata.get("vmid")
            if vmid:
                client.srem(f"vmid_sessions:{vmid}", token)
                active_count = client.scard(f"vmid_sessions:{vmid}")
                if active_count > 0:
                    is_last = False
        except Exception as e:
            logger.error(f"Error parsing session metadata for token {token}: {e}")
            
    client.delete(f"session_ttl:{token}")
    client.delete(shadow_key)
    logger.info(f"Deleted session for token: {token}. VMID: {vmid}. Last active session: {is_last}")
    return is_last


# Job Management (for provisioning tasks)
# job:{job_id} -> Hash or JSON of the job status

def set_job_status(job_id: str, status: str, error: Optional[str] = None, 
                   token: Optional[str] = None, vmid: Optional[int] = None, 
                   lxc_ip: Optional[str] = None, proxy_url: Optional[str] = None,
                   container_data_path: Optional[str] = None) -> None:
    client = get_redis_client()
    job_key = f"job:{job_id}"
    
    job_data = {
        "job_id": job_id,
        "status": status,
        "updated_at": time.time()
    }
    if error:
        job_data["error"] = error
    if token:
        job_data["token"] = token
    if vmid:
        job_data["vmid"] = vmid
    if lxc_ip:
        job_data["lxc_ip"] = lxc_ip
    if proxy_url:
        job_data["proxy_url"] = proxy_url
    if container_data_path:
        job_data["container_data_path"] = container_data_path
        
    client.set(job_key, json.dumps(job_data), ex=86400)  # Keep jobs for 24h
    
    # Publish update to channel for WebSockets/SSE clients
    channel_key = f"job_channel:{job_id}"
    client.publish(channel_key, json.dumps(job_data))
    logger.info(f"Job {job_id} status updated to: {status}")


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    client = get_redis_client()
    job_key = f"job:{job_id}"
    data = client.get(job_key)
    if data:
        return json.loads(data)
    return None


# Background Keyspace Event Listener
class RedisExpiredListener(threading.Thread):
    def __init__(self):
        super().__init__(name="RedisExpiredListener", daemon=True)
        self.client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._stop_event = threading.Event()
        
    def stop(self) -> None:
        self._stop_event.set()
        
    def run(self) -> None:
        logger.info("Starting Redis Expired Keyspace Event Listener...")
        
        # Configure Redis keyspace notifications
        try:
            self.client.config_set("notify-keyspace-events", "Ex")
            logger.info("Keyspace notifications (Ex) enabled successfully on Redis")
        except Exception as e:
            logger.warning(
                f"Could not enable keyspace notifications on Redis. "
                f"Ensure notify-keyspace-events is set to 'Ex' in redis.conf: {e}"
            )
            
        pubsub = self.client.pubsub()
        # Subscribe to the keyspace expiration channel
        pubsub.psubscribe("__keyevent@*__:expired")
        
        last_sweep_time = time.time()
        while not self._stop_event.is_set():
            try:
                # 1. Listen for keyspace notifications (with 1.0s timeout)
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "pmessage":
                    key = message.get("data")
                    if key and key.startswith("session_ttl:"):
                        token = key.split("session_ttl:")[1]
                        logger.info(f"Keyspace Event: Session expired for token: {token}")
                        self._handle_session_expired(token)
                
                # 2. Fallback sweep: actively check for expired sessions every 5 minutes (300 seconds)
                now = time.time()
                if now - last_sweep_time > 300:
                    last_sweep_time = now
                    self._perform_expired_sessions_sweep()
                    
            except Exception as e:
                logger.error(f"Error in RedisExpiredListener loop: {e}")
                time.sleep(2)
                
        pubsub.close()
        logger.info("Redis Expired Keyspace Event Listener stopped.")

    def _perform_expired_sessions_sweep(self) -> None:
        logger.info("Performing active fallback sweep to identify expired sessions...")
        try:
            # Use SCAN to iterate over all "session:*" keys in Redis
            for key in self.client.scan_iter("session:*"):
                token = key.split("session:")[1]
                ttl_key = f"session_ttl:{token}"
                # If the ttl key does not exist, the session has expired
                if not self.client.exists(ttl_key):
                    logger.warning(f"Fallback Sweep: Expired session detected (no TTL key): token={token}. Cleaning up.")
                    self._handle_session_expired(token)
        except Exception as e:
            logger.error(f"Error during expired sessions fallback sweep: {e}")

    def _handle_session_expired(self, token: str) -> None:
        shadow_key = f"session:{token}"
        data_str = self.client.get(shadow_key)
        if not data_str:
            logger.warning(f"Metadata not found for expired token: {token}")
            return
            
        try:
            metadata = json.loads(data_str)
            vmid = metadata.get("vmid")
            node = metadata.get("node")
            data_path = metadata.get("data_path")
            
            # Remove expired token from VMID active sessions set
            if vmid:
                self.client.srem(f"vmid_sessions:{vmid}", token)
                active_count = self.client.scard(f"vmid_sessions:{vmid}")
                logger.info(f"Keyspace Event: Session expired for token: {token}. VMID={vmid}. Active count left: {active_count}")
                
                if active_count == 0:
                    logger.info(f"Triggering container destruction for expired session {token}: VMID={vmid}, Node={node}, Path={data_path}")
                    # Import celery task dynamically to avoid circular dependencies
                    from app.tasks import destroy_container_task
                    destroy_container_task.delay(vmid, node)
                else:
                    logger.info(f"VMID {vmid} has {active_count} remaining active sessions. Not stopping container.")
            
        except Exception as e:
            logger.error(f"Failed to process expired session for token {token}: {e}")
        finally:
            # Delete shadow key
            self.client.delete(shadow_key)
