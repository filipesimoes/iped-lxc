import asyncio
import json
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status, Query
from sse_starlette.sse import EventSourceResponse
import redis.asyncio as aioredis
from app.config import settings
from app.schemas import InstanceStart, JobStatusResponse
from app.redis_state import get_job_status, get_session, delete_session, set_job_status
from app.tasks import provision_container_task, destroy_container_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/instances/start", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED, summary="Start an IPED instance")
async def start_instance(payload: InstanceStart):
    """
    Starts a pre-configured IPED container instance.
    Starts an asynchronous provisioning Celery task.
    Returns a Job ID immediately.
    """
    job_id = str(uuid.uuid4())
    logger.info(f"Received request to start container with VMID: {payload.vmid}. Generated job_id: {job_id}")
    
    # Save initial status
    set_job_status(job_id, "Pending", vmid=payload.vmid)
    
    # Spawn Celery Task
    provision_container_task.delay(
        job_id,
        payload.vmid,
        payload.proxmox_node,
        payload.proxmox_bridge,
        payload.iped_api_key
    )
    
    return JobStatusResponse(
        job_id=job_id,
        status="Pending"
    )



@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """
    Returns the current status of the provisioning job.
    """
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provisioning job with ID {job_id} not found."
        )
    job.pop("lxc_ip", None)
    return JobStatusResponse(**job)


@router.delete("/instances/{token}", status_code=status.HTTP_200_OK, summary="Stop an IPED instance")
async def stop_instance(token: str):
    """
    Manually stops the running IPED container instance.
    """
    session = get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or already expired."
        )
        
    vmid = session.get("vmid")
    node = session.get("node")
    
    logger.info(f"Manual stop request for token {token}. VMID: {vmid}, Node: {node}")
    
    # Delete session from Redis and check if it is the last active session
    is_last = delete_session(token)
    
    if is_last:
        # Trigger stop task in background
        destroy_container_task.delay(vmid, node)
        return {"status": "stopped", "message": f"Stop triggered for container VMID {vmid}."}
    else:
        logger.info(f"Session {token} removed, but VMID {vmid} has other active sessions. Container remains running.")
        return {"status": "session_removed", "message": f"Session removed. Container VMID {vmid} remains running for other active users."}



@router.websocket("/jobs/{job_id}/ws")
async def job_status_websocket(
    websocket: WebSocket,
    job_id: str,
    api_key: Optional[str] = Query(None, description="The API Key required to authenticate WebSocket connection")
):
    """
    WebSocket endpoint that streams real-time provisioning updates from Redis Pub/Sub.
    """
    # 1. Authenticate WebSocket connection manually
    if api_key != settings.API_KEY:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(f"WebSocket connection rejected for job {job_id}: Invalid or missing API Key.")
        return

    await websocket.accept()
    logger.info(f"WebSocket client connected for job: {job_id}")
    
    # Initialize async Redis connection
    redis_conn = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_conn.pubsub()
    channel = f"job_channel:{job_id}"
    await pubsub.subscribe(channel)
    
    # Check current status first to prevent race condition where client connects
    # after the task has already made progress or finished.
    current_status = get_job_status(job_id)
    if current_status:
        current_status.pop("lxc_ip", None)
        current_status.pop("token", None)
        current_status.pop("proxy_url", None)
        await websocket.send_json(current_status)
        if current_status.get("status") in ["Ready", "Failed"]:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await redis_conn.close()
            await websocket.close()
            return
            
    try:
        while True:
            # Check for messages on the channel (with 1s timeout to allow loop evaluation)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = json.loads(message["data"])
                data.pop("lxc_ip", None)
                data.pop("token", None)
                data.pop("proxy_url", None)
                await websocket.send_json(data)
                if data.get("status") in ["Ready", "Failed"]:
                    break
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for job: {job_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket status stream for job {job_id}: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_conn.close()
        try:
            await websocket.close()
        except RuntimeError:
            # WebSocket might be already closed
            pass


@router.get("/jobs/{job_id}/sse")
async def job_status_sse(job_id: str):
    """
    SSE endpoint that streams real-time provisioning updates from Redis Pub/Sub.
    """
    async def event_generator():
        redis_conn = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = redis_conn.pubsub()
        channel = f"job_channel:{job_id}"
        await pubsub.subscribe(channel)
        
        # Check current status first
        current_status = get_job_status(job_id)
        if current_status:
            current_status.pop("lxc_ip", None)
            current_status.pop("token", None)
            current_status.pop("proxy_url", None)
            yield {
                "event": "status",
                "data": json.dumps(current_status)
            }
            if current_status.get("status") in ["Ready", "Failed"]:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                await redis_conn.close()
                return
                
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    data = json.loads(message["data"])
                    data.pop("lxc_ip", None)
                    data.pop("token", None)
                    data.pop("proxy_url", None)
                    yield {
                        "event": "status",
                        "data": json.dumps(data)
                    }
                    if data.get("status") in ["Ready", "Failed"]:
                        break
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info(f"SSE client disconnected for job: {job_id}")
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await redis_conn.close()
            
    return EventSourceResponse(event_generator())
