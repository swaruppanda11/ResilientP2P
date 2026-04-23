from fastapi import Depends, FastAPI, HTTPException, Query
import asyncio
import logging
import os

from common.auth import AuthContext, require_auth
from common.config import get_peer_settings
from common.logging import get_logger, log_event
from common.schemas import HealthResponse, PeerFetchResponse, PeerStatsResponse
from dht.node import DHTNode
from peer.cache import Cache
from peer.client import PeerClient
from contextlib import asynccontextmanager

settings = get_peer_settings()
logger = get_logger(f"{settings.service_name}:{settings.peer_id}")

cache = Cache(capacity_bytes=settings.cache_capacity_bytes)
dht_node = DHTNode(port=settings.dht_port, logger=logger)
client = PeerClient(
    settings.peer_id,
    settings.location_id,
    settings.coordinator_url,
    settings.origin_url,
    cache,
    dht_node,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Start DHT node and bootstrap into the overlay.
    bootstrap_nodes = []
    if settings.dht_bootstrap_host:
        bootstrap_nodes = [(settings.dht_bootstrap_host, settings.dht_bootstrap_port)]
    await dht_node.start(bootstrap_nodes)

    # 2. Register with coordinator
    await client.register(settings.host, settings.port)

    # 3. Background tasks: heartbeat + DHT republish
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    republish_task = asyncio.create_task(republish_loop())
    rebootstrap_task = asyncio.create_task(rebootstrap_loop())

    yield

    heartbeat_task.cancel()
    republish_task.cancel()
    rebootstrap_task.cancel()
    # Graceful DHT departure: remove self from provider lists.
    await dht_node.remove_peer(settings.peer_id, list(cache.storage.keys()))
    dht_node.stop()

async def heartbeat_loop():
    while True:
        await client.heartbeat()
        await asyncio.sleep(settings.heartbeat_interval_seconds)

async def republish_loop():
    """Periodically re-announce cached objects to the DHT (churn recovery)."""
    while True:
        await asyncio.sleep(settings.dht_republish_interval_seconds)
        await client.republish_all()

async def rebootstrap_loop():
    """Periodically retry DHT bootstrap so peers recover from startup races."""
    while True:
        await asyncio.sleep(settings.dht_rebootstrap_interval_seconds)
        await dht_node.bootstrap_once()

app = FastAPI(title=f"Peer {settings.peer_id}", lifespan=lifespan)

@app.get("/get-object/{object_id}")
async def get_object(
    object_id: str,
    requester_location_id: str = Query(...),
    auth: AuthContext = Depends(require_auth),
):
    data = cache.get(object_id)
    if not data:
        raise HTTPException(status_code=404, detail="Object not in cache")

    metadata = cache.get_metadata(object_id)
    if metadata is not None and metadata.visibility == "restricted":
        if not auth.peer_group or auth.peer_group not in (metadata.allowed_groups or []):
            log_event(
                logger, logging.WARNING, "get_object_forbidden",
                peer_id=settings.peer_id, object_id=object_id,
                claimed_group=auth.peer_group,
            )
            raise HTTPException(status_code=403, detail="forbidden")

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
    # Do not block the data-plane response on coordinator-side accounting.
    asyncio.create_task(client.report_transfer(object_id, len(data)))
    return {
        "content_hex": data.hex(),
        "metadata": metadata.dict() if metadata else None,
    }


@app.post("/invalidate/{object_id}")
async def invalidate_object(object_id: str, _: AuthContext = Depends(require_auth)):
    removed = cache.invalidate(object_id)
    await dht_node.remove_peer(settings.peer_id, [object_id])
    log_event(
        logger,
        logging.INFO,
        "cache_invalidated",
        peer_id=settings.peer_id,
        object_id=object_id,
        removed=removed,
    )
    return {"status": "invalidated", "object_id": object_id, "removed": removed}


@app.post("/invalidate-prefix")
async def invalidate_prefix(prefix: str = Query(...), _: AuthContext = Depends(require_auth)):
    removed_object_ids = cache.invalidate_prefix(prefix)
    await dht_node.remove_peer(settings.peer_id, removed_object_ids)
    log_event(
        logger,
        logging.INFO,
        "cache_prefix_invalidated",
        peer_id=settings.peer_id,
        prefix=prefix,
        removed_object_count=len(removed_object_ids),
    )
    return {
        "status": "invalidated",
        "prefix": prefix,
        "removed_object_ids": removed_object_ids,
    }

@app.post("/suicide")
async def suicide(_: AuthContext = Depends(require_auth)):
    # Simulate a crash
    print("Suicide requested. Stopping peer...")
    os._exit(0)

@app.get("/trigger-fetch/{object_id}", response_model=PeerFetchResponse)
async def trigger_fetch(
    object_id: str,
    version: str | None = Query(default=None),
    cacheability: str | None = Query(default=None),
    max_age_seconds: int | None = Query(default=None),
    _: AuthContext = Depends(require_auth),
):
    result = await client.fetch_object(
        object_id,
        version=version,
        cacheability=cacheability,
        max_age_seconds=max_age_seconds,
    )
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
async def stats(_: AuthContext = Depends(require_auth)):
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
