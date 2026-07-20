import logging
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.redis_state import RedisExpiredListener
from app.routers import provision, proxy
from app.dependencies import verify_api_key

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="IPED LXC Wrapper API",
    description="Orchestrates IPED API instances in Proxmox LXC containers and handles transparent proxy routing with session token validation.",
    version="1.0.0",
    dependencies=[Depends(verify_api_key)]
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    logger.info("Initializing IPED LXC Wrapper...")
    logger.info(f"Configuration Mode: {'MOCK (Development)' if settings.MOCK_MODE else 'PRODUCTION (Proxmox VE)'}")
    
    # Start Redis Keyspace Expiration Listener in a background thread
    try:
        listener = RedisExpiredListener()
        listener.start()
        app.state.redis_listener = listener
        logger.info("Started RedisExpiredListener thread.")
    except Exception as e:
        logger.error(f"Failed to start Redis keyspace listener: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Stopping IPED LXC Wrapper...")
    
    # Stop the Redis listener thread
    if hasattr(app.state, "redis_listener"):
        logger.info("Stopping RedisExpiredListener thread...")
        app.state.redis_listener.stop()
        # Daemon thread will clean up automatically


@app.get("/ping", tags=["Health"])
async def ping():
    return {"ping": "pong", "mock_mode": settings.MOCK_MODE}


# Include Routers
app.include_router(provision.router, prefix="/v1", tags=["Instance Management"])
app.include_router(proxy.router, prefix="/proxy", tags=["Proxy Routing"])

