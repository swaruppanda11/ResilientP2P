from fastapi import FastAPI, HTTPException, Query
import asyncio
import hashlib
import time

from common.config import get_origin_settings
from common.schemas import HealthResponse

app = FastAPI(title="Origin Server")
settings = get_origin_settings()

# Helper to generate deterministic data based on object_id
def generate_content(object_id: str, size: int = 1024):
    # Use object_id to seed or just hash it to get fixed "content"
    base = object_id.encode()
    content = base * (size // len(base)) + base[:size % len(base)]
    checksum = hashlib.sha256(content).hexdigest()
    return content, checksum

@app.get("/object/{object_id}")
async def get_object(object_id: str, delay: float | None = Query(None)):
    # Simulate WAN delay
    effective_delay_seconds = (
        delay if delay is not None else settings.origin_delay_ms / 1000
    )
    if effective_delay_seconds > 0:
        await asyncio.sleep(effective_delay_seconds)
    
    # For now, let's assume a fixed size of 1MB for all objects
    content, checksum = generate_content(object_id, size=1024 * 1024)
    
    return {
        "object_id": object_id,
        "content_hex": content.hex(), 
        "checksum": checksum,
        "size": len(content)
    }

@app.get("/metadata/{object_id}")
async def get_metadata(object_id: str):
    content, checksum = generate_content(object_id, size=1024 * 1024)
    return {
        "object_id": object_id,
        "checksum": checksum,
        "size_bytes": len(content)
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service="origin")
