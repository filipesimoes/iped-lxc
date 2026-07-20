import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, status, Path, Query
from fastapi.responses import StreamingResponse
import httpx
from app.config import settings
from app.redis_state import get_session, refresh_session

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared long-lived async HTTP client to prevent port/socket exhaustion
# Timeout is set to 10 minutes (600s) to allow long-running forensic operations
http_client = httpx.AsyncClient(timeout=600.0)


async def _forward_request(
    token: str,
    path: str,
    request: Request,
    override_accept: Optional[str] = None
) -> StreamingResponse:
    """
    Validates token, refreshes session TTL (sliding window), 
    and proxies requests to the target LXC container IPED instance.
    """
    # 1. Validate session token
    session = get_session(token)
    if not session:
        logger.warning(f"Unauthorized proxy attempt with invalid/expired token: {token}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or token is invalid."
        )
        
    # 2. Refresh the TTL on proxy access (sliding window timeout)
    refresh_session(token)
    
    lxc_ip = session.get("lxc_ip")
    if not lxc_ip:
        logger.error(f"Session data corrupted: lxc_ip is missing for token: {token}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session configuration error: LXC IP is missing."
        )
        
    # 3. Formulate the destination URL
    # Combine internal IP, IPED API port, route path, and query parameters
    query_string = request.url.query
    destination_url = f"http://{lxc_ip}:{settings.IPED_API_PORT}/{path}"
    if query_string:
        destination_url = f"{destination_url}?{query_string}"
        
    logger.info(f"Proxying request: {request.method} /{path} -> {destination_url}")
    
    # 4. Read the incoming request headers and filter out control fields
    # Host header must be omitted to let HTTPX generate the correct one for the target
    # Content-Length is omitted because HTTPX will calculate it based on the parsed body
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() not in ["host", "content-length", "x-api-key"]
    }
    if override_accept:
        headers = {k: v for k, v in headers.items() if k.lower() != "accept"}
        headers["Accept"] = override_accept
        
    iped_api_key = session.get("iped_api_key")
    if iped_api_key:
        headers["X-API-Key"] = iped_api_key


    
    # 5. Read body content
    body = await request.body()
    
    # 6. Build the proxy request
    proxy_request = http_client.build_request(
        method=request.method,
        url=destination_url,
        headers=headers,
        content=body
    )
    
    # 7. Forward and stream the response
    try:
        proxy_response = await http_client.send(proxy_request, stream=True)
    except httpx.ConnectError as e:
        logger.error(f"LXC IPED container at {lxc_ip} is unreachable: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Container is unreachable. The IPED API instance may be starting or offline."
        )
    except Exception as e:
        logger.error(f"Error forwarding request to container: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Bad Gateway: Failed to forward request. {e}"
        )
        
    # 8. Return StreamingResponse
    # Content-Length is filtered out from response because Uvicorn uses chunked transfer
    # encoding for StreamingResponse, and Content-Length presence causes parser issues.
    # Connection is filtered out to let uvicorn negotiate connection lifecycle.
    response_headers = {
        k: v for k, v in proxy_response.headers.items()
        if k.lower() not in ["content-length", "connection"]
    }
    
    return StreamingResponse(
        proxy_response.aiter_raw(),
        status_code=proxy_response.status_code,
        headers=response_headers,
        media_type=proxy_response.headers.get("content-type")
    )


@router.get("/{token}/sources", summary="Retrieve all forensic sources")
async def get_sources(
    request: Request,
    token: str = Path(..., description="The session token for the container instance")
):
    """
    Lists the forensic image sources loaded in the IPED instance.
    """
    return await _forward_request(token, "sources", request)


@router.get("/{token}/sources/{sourceID}/docs/{doc_id}", summary="Get properties of a specific document")
async def get_document(
    request: Request,
    token: str = Path(..., description="The session token for the container instance"),
    sourceID: str = Path(..., description="The ID of the forensic source"),
    doc_id: str = Path(..., description="The document unique identifier"),
    field: str = Query(None, description="Optional specific field to retrieve from the document")
):
    """
    Retrieves metadata/properties for a single document, or optionally a specific field value.
    """
    return await _forward_request(token, f"sources/{sourceID}/docs/{doc_id}", request)


@router.get("/{token}/sources/{sourceID}/docs/{doc_id}/content", summary="Stream raw document content")
async def get_document_content(
    request: Request,
    token: str = Path(..., description="The session token for the container instance"),
    sourceID: str = Path(..., description="The ID of the forensic source"),
    doc_id: str = Path(..., description="The document unique identifier")
):
    """
    Downloads or streams the binary content of the specified document.
    """
    return await _forward_request(token, f"sources/{sourceID}/docs/{doc_id}/content", request, override_accept="*/*")


@router.get("/{token}/sources/{sourceID}/docs/{doc_id}/text", summary="Stream extracted text content")
async def get_document_text(
    request: Request,
    token: str = Path(..., description="The session token for the container instance"),
    sourceID: str = Path(..., description="The ID of the forensic source"),
    doc_id: str = Path(..., description="The document unique identifier")
):
    """
    Downloads or streams the text content extracted from the document.
    """
    return await _forward_request(token, f"sources/{sourceID}/docs/{doc_id}/text", request, override_accept="*/*")


@router.get("/{token}/search", summary="Search documents")
async def search(
    request: Request,
    token: str = Path(..., description="The session token for the container instance"),
    q: Optional[str] = Query(None, description="Search query string"),
    sourceID: Optional[str] = Query(None, description="Filter by source ID"),
    sort: Optional[str] = Query(None, description="Sort parameter (comma-separated fields, prefix with '-' for descending)")
):
    """
    Executes a search query against index documents, with optional source filtering and sorting.
    """
    return await _forward_request(token, "search", request)
