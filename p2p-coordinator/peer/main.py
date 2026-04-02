from fastapi import FastAPI, HTTPException, Query
import asyncio
import logging
import os

from common.config import get_peer_settings
from common.logging import get_logger, log_event
from common.schemas import HealthResponse, PeerFetchResponse, PeerStatsResponse
from peer.cache import Cache
from peer.client import PeerClient
from contextlib import asynccontextmanager

settings = get_peer_settings()
logger = get_logger(f"{settings.service_name}:{settings.peer_id}")

cache = Cache(capacity_bytes=settings.cache_capacity_bytes)
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
async def get_object(object_id: str, requester_location_id: str = Query(...)):
    data = cache.get(object_id)
    if not data:
        raise HTTPException(status_code=404, detail="Object not in cache")

    if requester_location_id == settings.location_id:
        delay_ms = settings.intra_location_delay_ms
    else:
        delay_ms = settings.inter_location_delay_ms
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    log_event(
        logger,
        logging.INFO,
        "cache_served",
        peer_id=settings.peer_id,
        object_id=object_id,
        size_bytes=len(data),
        requester_location_id=requester_location_id,
        network_delay_ms=delay_ms,
    )
    await client.report_transfer(object_id, len(data))
    return {"content_hex": data.hex()}

@app.post("/suicide")
async def suicide():
    # Simulate a crash
    print("Suicide requested. Stopping peer...")
    os._exit(0)

@app.get("/trigger-fetch/{object_id}", response_model=PeerFetchResponse)
async def trigger_fetch(object_id: str):
    result = await client.fetch_object(object_id)
    if result:
        return PeerFetchResponse(
            status="success",
            object_id=object_id,
            source=result.source,
            size=result.size,
            latency_ms=result.latency_ms,
            candidate_count=result.candidate_count,
            provider=result.provider,
        )
    return PeerFetchResponse(
        status="failed",
        object_id=object_id,
        source="none",
        size=0,
        latency_ms=0.0,
        candidate_count=0,
        provider=None,
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service=f"{settings.service_name}:{settings.peer_id}")


@app.get("/stats", response_model=PeerStatsResponse)
async def stats():
    cache_stats = cache.get_stats()
    return PeerStatsResponse(
        status="ok",
        service=f"{settings.service_name}:{settings.peer_id}",
        peer_id=settings.peer_id,
        location_id=settings.location_id,
        cache_capacity_bytes=cache_stats["capacity_bytes"],
        cache_size_bytes=cache_stats["current_size_bytes"],
        cache_object_count=cache_stats["object_count"],
        cache_hit_count=cache_stats["hit_count"],
        cache_miss_count=cache_stats["miss_count"],
        cache_eviction_count=cache_stats["eviction_count"],
        cache_rejected_write_count=cache_stats["rejected_write_count"],
    )
