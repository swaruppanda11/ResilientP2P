from fastapi import FastAPI, HTTPException
import asyncio
import logging
import os

from common.config import get_peer_settings
from common.logging import get_logger, log_event
from common.schemas import HealthResponse
from peer.cache import Cache
from peer.client import PeerClient
from contextlib import asynccontextmanager

settings = get_peer_settings()
logger = get_logger(f"{settings.service_name}:{settings.peer_id}")

cache = Cache()
client = PeerClient(
    settings.peer_id,
    settings.location_id,
    settings.coordinator_url,
    settings.origin_url,
    cache,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Register with coordinator
    await client.register(settings.host, settings.port)
    
    # 2. Start heartbeat loop
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    
    yield
    heartbeat_task.cancel()

async def heartbeat_loop():
    while True:
        await client.heartbeat()
        await asyncio.sleep(settings.heartbeat_interval_seconds)

app = FastAPI(title=f"Peer {settings.peer_id}", lifespan=lifespan)

@app.get("/get-object/{object_id}")
async def get_object(object_id: str):
    data = cache.get(object_id)
    if not data:
        raise HTTPException(status_code=404, detail="Object not in cache")
    log_event(
        logger,
        logging.INFO,
        "cache_served",
        peer_id=settings.peer_id,
        object_id=object_id,
        size_bytes=len(data),
    )
    return {"content_hex": data.hex()}

@app.post("/suicide")
async def suicide():
    # Simulate a crash
    print("Suicide requested. Stopping peer...")
    os._exit(0)

@app.get("/trigger-fetch/{object_id}")
async def trigger_fetch(object_id: str):
    data = await client.fetch_object(object_id)
    if data:
        return {"status": "success", "size": len(data)}
    return {"status": "failed"}


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service=f"{settings.service_name}:{settings.peer_id}")
