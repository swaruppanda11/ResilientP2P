import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from common.config import get_dht_peer_settings
from common.logging import get_logger, log_event
from common.schemas import HealthResponse, PeerFetchResponse, PeerStatsResponse
from dht.node import DHTNode
from peer.cache import Cache
from peer.client import DHTPeerClient

settings = get_dht_peer_settings()
logger = get_logger(f"dht-peer:{settings.peer_id}")

cache = Cache(capacity_bytes=settings.cache_capacity_bytes)
dht_node = DHTNode(port=settings.dht_port, logger=logger)
client = DHTPeerClient(
    peer_id=settings.peer_id,
    location_id=settings.location_id,
    dht_node=dht_node,
    coordinator_url=settings.coordinator_url,
    origin_url=settings.origin_url,
    cache=cache,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Start DHT node and bootstrap into the overlay.
    bootstrap_nodes = []
    if settings.dht_bootstrap_host:
        bootstrap_nodes = [(settings.dht_bootstrap_host, settings.dht_bootstrap_port)]
    await dht_node.start(bootstrap_nodes)

    # 2. Register with coordinator so the fallback index is populated.
    await client.register(settings.host, settings.port)

    # 3. Background tasks: heartbeat (coordinator liveness) + DHT republish.
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    republish_task = asyncio.create_task(_republish_loop())

    yield

    heartbeat_task.cancel()
    republish_task.cancel()
    # Graceful DHT departure: remove self from provider lists.
    await dht_node.remove_peer(settings.peer_id, list(cache.storage.keys()))
    dht_node.stop()


async def _heartbeat_loop() -> None:
    while True:
        await client.heartbeat()
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def _republish_loop() -> None:
    """Periodically re-announce cached objects to the DHT (churn recovery)."""
    while True:
        await asyncio.sleep(settings.dht_republish_interval_seconds)
        await client.republish_all()


app = FastAPI(title=f"DHT Peer {settings.peer_id}", lifespan=lifespan)


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
        logger, logging.INFO, "cache_served",
        peer_id=settings.peer_id, object_id=object_id, size_bytes=len(data),
        requester_location_id=requester_location_id, network_delay_ms=delay_ms,
    )
    # Keep peer-to-peer serving independent from coordinator accounting.
    asyncio.create_task(client.report_transfer(object_id, len(data)))
    return {"content_hex": data.hex()}


@app.post("/suicide")
async def suicide():
    """Abrupt crash simulation used by the experiment runner."""
    print("Suicide requested. Stopping DHT peer...")
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
    return HealthResponse(status="ok", service=f"dht-peer:{settings.peer_id}")


@app.get("/stats", response_model=PeerStatsResponse)
async def stats():
    cache_stats = cache.get_stats()
    return PeerStatsResponse(
        status="ok",
        service=f"dht-peer:{settings.peer_id}",
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
