from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.config import settings

# Setup security scheme (header only)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(
    api_key_h: str = Security(api_key_header)
):
    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key is not configured on the server."
        )
    
    # Check if the header matches the configured API key
    if api_key_h == settings.API_KEY:
        return api_key_h
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API Key."
    )
