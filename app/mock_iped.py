import io
from typing import Optional
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import StreamingResponse

app = FastAPI(
    title="Mock IPED API",
    description="Simulates the IPED Engine REST API endpoints for testing proxy and health checks.",
    version="4.3.1"
)


@app.get("/ping")
async def ping():
    return {"ping": "pong", "engine": "IPED Mock Engine", "status": "idle"}


@app.get("/sources")
async def get_sources():
    return [
        {
            "id": "src-001",
            "name": "Forensic_Image_A.E01",
            "size": 1548293021,
            "type": "EWF"
        },
        {
            "id": "src-002",
            "name": "Disk_Image_B.raw",
            "size": 4294967296,
            "type": "RAW"
        }
    ]


@app.get("/sources/{sourceID}/docs/{doc_id}")
async def get_document(
    sourceID: str = Path(..., description="The ID of the forensic source"),
    doc_id: str = Path(..., description="The document unique identifier"),
    field: Optional[str] = Query(None, description="Optional specific field to retrieve")
):
    try:
        numeric_id = int(doc_id)
    except ValueError:
        numeric_id = 9999

    if field:
        return {
            "id": numeric_id,
            "sourceID": sourceID,
            "field_name": field,
            "field_value": f"Mock value for {field}"
        }
        
    return {
        "source": sourceID,
        "id": numeric_id,
        "luceneId": numeric_id * 10,
        "properties": {
            "name": [f"evidence_document_{doc_id[:8]}.pdf"],
            "size": ["245102"],
            "contentType": ["application/pdf"],
            "path": [f"/data/extracted/{sourceID}/{doc_id[:8]}"],
            "hash": ["8b1a8c88bf2a5e8e97f0a8d6e3c0b11a"]
        },
        "bookmarks": [],
        "selected": False
    }


@app.get("/sources/{sourceID}/docs/{doc_id}/content")
async def get_document_content(
    sourceID: str = Path(...),
    doc_id: str = Path(...)
):
    # Return a dummy PDF/binary stream
    dummy_content = b"%PDF-1.4 ... Mock Binary Content for Doc " + doc_id.encode()
    return StreamingResponse(
        io.BytesIO(dummy_content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=doc_{doc_id[:8]}.pdf"}
    )


@app.get("/sources/{sourceID}/docs/{doc_id}/text")
async def get_document_text(
    sourceID: str = Path(...),
    doc_id: str = Path(...)
):
    # Return a dummy text stream
    dummy_text = f"This is the mock extracted text content for document {doc_id} from source {sourceID}.\n" \
                 f"IPED OCR was simulated and successfully processed this file."
    return StreamingResponse(
        io.BytesIO(dummy_text.encode("utf-8")),
        media_type="text/plain; charset=utf-8"
    )


@app.get("/search")
async def search(
    q: Optional[str] = Query(None, description="Search query string"),
    sourceID: Optional[str] = Query(None, description="Filter by source ID"),
    sort: Optional[str] = Query(None, description="Sort parameter (comma-separated fields, prefix with '-' for descending)")
):
    return {
        "data": [
            {
                "source": sourceID or "src-001",
                "ids": [1001, 1002]
            }
        ]
    }
