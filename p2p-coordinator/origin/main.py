from fastapi import FastAPI, HTTPException, Query
import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone

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
async def get_object(
    object_id: str,
    delay: float | None = Query(None),
    version: str = Query("1"),
    cacheability: str = Query("immutable"),
    max_age_seconds: int | None = Query(None),
):
    # Simulate WAN delay
    effective_delay_seconds = (
        delay if delay is not None else settings.origin_delay_ms / 1000
    )
    if effective_delay_seconds > 0:
        await asyncio.sleep(effective_delay_seconds)
    
    # For now, let's assume a fixed size of 1MB for all objects
    content_key = object_id if version == "1" else f"{object_id}:v{version}"
    content, checksum = generate_content(content_key, size=1024 * 1024)
    expires_at = None
    if max_age_seconds is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)
    
    return {
        "object_id": object_id,
        "content_hex": content.hex(), 
        "checksum": checksum,
        "size": len(content),
        "version": version,
        "cacheability": cacheability,
        "max_age_seconds": max_age_seconds,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "etag": checksum,
    }

@app.get("/metadata/{object_id}")
async def get_metadata(
    object_id: str,
    version: str = Query("1"),
    cacheability: str = Query("immutable"),
    max_age_seconds: int | None = Query(None),
):
    content_key = object_id if version == "1" else f"{object_id}:v{version}"
    content, checksum = generate_content(content_key, size=1024 * 1024)
    expires_at = None
    if max_age_seconds is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)
    return {
        "object_id": object_id,
        "checksum": checksum,
        "size_bytes": len(content),
        "version": version,
        "cacheability": cacheability,
        "max_age_seconds": max_age_seconds,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "etag": checksum,
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service="origin")
