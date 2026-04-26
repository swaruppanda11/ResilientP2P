import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from common.auth import AuthContext, outbound_auth, require_auth


def _enforce_peer_id_match(claimed: str, body_peer_id: str) -> None:
    """Block a peer from acting as another peer (WS2 follow-up bug fix).

    When the caller asserted an identity, the body's `peer_id` field must
    match it. Skipped when no identity is asserted (AUTH_MODE=none with no
    X-Peer-Id header) to preserve backwards compatibility.
    """
    if claimed is None:
        return
    if claimed != body_peer_id:
        raise HTTPException(
            status_code=403,
            detail={
                "detail": f"body peer_id '{body_peer_id}' does not match authenticated peer '{claimed}'",
                "error_code": "peer_id_mismatch",
            },
        )
from common.config import get_coordinator_settings
from common.logging import get_logger, log_event
from common.schemas import (
    BadPeerReportRequest,
    BadPeerReportResponse,
    CoordinatorStatsResponse,
    ErrorResponse,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    InvalidateResponse,
    LookupResponse,
    PeerReputationSnapshot,
    PublishRequest,
    PublishResponse,
    RegisterRequest,
    RegisterResponse,
    TransferReportRequest,
    TransferReportResponse,
)
from coordinator.reputation import ReputationTracker
from coordinator.store import (
    DuplicatePeerError,
    InvalidPublishError,
    QuarantinedPublisherError,
    Store,
    UnknownPeerError,
)
import asyncio

settings = get_coordinator_settings()
logger = get_logger(settings.service_name)
reputation_tracker = ReputationTracker(settings.reputation)
store = Store(
    max_providers_per_lookup=settings.max_providers_per_lookup,
    provider_selection_policy=settings.provider_selection_policy,
    reputation=reputation_tracker if settings.reputation.enabled else None,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    yield
    cleanup_task.cancel()

async def periodic_cleanup():
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        store.cleanup(timeout_seconds=settings.peer_timeout_seconds)
        # WS3: drive quarantined→healthy cooldown transitions on the same timer
        # the peer-eviction loop already runs on. No-op when reputation disabled.
        if settings.reputation.enabled:
            recovered = reputation_tracker.tick_cooldowns()
            for peer_id in recovered:
                log_event(
                    logger, logging.INFO, "reputation_recovered",
                    peer_id=peer_id,
                )

app = FastAPI(title="P2P Coordinator", lifespan=lifespan)

@app.exception_handler(DuplicatePeerError)
async def handle_duplicate_peer(_, exc: DuplicatePeerError):
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(detail=str(exc), error_code=exc.error_code).dict(),
    )


@app.exception_handler(UnknownPeerError)
async def handle_unknown_peer(_, exc: UnknownPeerError):
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(detail=str(exc), error_code=exc.error_code).dict(),
    )


@app.exception_handler(InvalidPublishError)
async def handle_invalid_publish(_, exc: InvalidPublishError):
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(detail=str(exc), error_code=exc.error_code).dict(),
    )


@app.exception_handler(QuarantinedPublisherError)
async def handle_quarantined_publisher(_, exc: QuarantinedPublisherError):
    return JSONResponse(
        status_code=403,
        content=ErrorResponse(detail=str(exc), error_code=exc.error_code).dict(),
    )


@app.post(
    "/register",
    response_model=RegisterResponse,
    responses={409: {"model": ErrorResponse}},
)
async def register(req: RegisterRequest, auth: AuthContext = Depends(require_auth)):
    _enforce_peer_id_match(auth.peer_id, req.peer_id)
    peer = store.register_peer(req)
    log_event(
        logger,
        logging.INFO,
        "peer_registered",
        peer_id=peer.peer_id,
        location_id=peer.location_id,
        url=peer.url,
    )
    return RegisterResponse(status="registered", peer_id=peer.peer_id)


@app.post(
    "/publish",
    response_model=PublishResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def publish(req: PublishRequest, auth: AuthContext = Depends(require_auth)):
    _enforce_peer_id_match(auth.peer_id, req.peer_id)
    store.publish_object(req.peer_id, req.metadata)
    log_event(
        logger,
        logging.INFO,
        "object_published",
        peer_id=req.peer_id,
        object_id=req.metadata.object_id,
        size_bytes=req.metadata.size_bytes,
    )
    return PublishResponse(
        status="published",
        peer_id=req.peer_id,
        object_id=req.metadata.object_id,
    )

@app.get("/lookup/{object_id}", response_model=LookupResponse)
async def lookup(
    object_id: str,
    location_id: str = Query(...),
    version: str | None = Query(default=None),
    auth: AuthContext = Depends(require_auth),
):
    providers = store.get_providers(object_id, location_id, version=version)
    metadata = store.get_object_metadata(object_id, version=version)
    # Visibility gate: unify "exists but hidden" with "does not exist" so the
    # coordinator response can't be used to probe for restricted-object names.
    if metadata is not None and metadata.visibility == "restricted":
        if not auth.peer_group or auth.peer_group not in (metadata.allowed_groups or []):
            log_event(
                logger, logging.INFO, "object_lookup_hidden",
                object_id=object_id, location_id=location_id,
                claimed_group=auth.peer_group,
            )
            return LookupResponse(object_id=object_id, providers=[], metadata=None)
    log_event(
        logger,
        logging.INFO,
        "object_lookup",
        object_id=object_id,
        location_id=location_id,
        provider_count=len(providers),
    )
    return LookupResponse(
        object_id=object_id,
        providers=providers,
        metadata=metadata
    )


@app.post("/invalidate/{object_id}", response_model=InvalidateResponse)
async def invalidate(object_id: str, _: AuthContext = Depends(require_auth)):
    provider_urls, removed_provider_entries = store.invalidate_object(object_id)
    notified_peers = 0
    async with httpx.AsyncClient(timeout=1.0, auth=outbound_auth(peer_id=settings.service_name)) as client:
        for provider_url in provider_urls:
            try:
                resp = await client.post(f"{provider_url}/invalidate/{object_id}")
                resp.raise_for_status()
                notified_peers += 1
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "peer_invalidation_failed",
                    object_id=object_id,
                    provider=provider_url,
                    error=str(exc),
                )

    log_event(
        logger,
        logging.INFO,
        "object_invalidated",
        object_id=object_id,
        removed_provider_entries=removed_provider_entries,
        notified_peers=notified_peers,
    )
    return InvalidateResponse(
        status="invalidated",
        object_id=object_id,
        removed_provider_entries=removed_provider_entries,
        notified_peers=notified_peers,
    )


@app.post("/invalidate-prefix")
async def invalidate_prefix(prefix: str = Query(...), _: AuthContext = Depends(require_auth)):
    provider_urls, removed_provider_entries, object_ids = store.invalidate_prefix(prefix)
    notified_peers = 0
    async with httpx.AsyncClient(timeout=1.0, auth=outbound_auth(peer_id=settings.service_name)) as client:
        for provider_url in provider_urls:
            try:
                resp = await client.post(
                    f"{provider_url}/invalidate-prefix",
                    params={"prefix": prefix},
                )
                resp.raise_for_status()
                notified_peers += 1
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "peer_prefix_invalidation_failed",
                    prefix=prefix,
                    provider=provider_url,
                    error=str(exc),
                )

    log_event(
        logger,
        logging.INFO,
        "object_prefix_invalidated",
        prefix=prefix,
        object_count=len(object_ids),
        removed_provider_entries=removed_provider_entries,
        notified_peers=notified_peers,
    )
    return {
        "status": "invalidated",
        "prefix": prefix,
        "object_ids": object_ids,
        "removed_provider_entries": removed_provider_entries,
        "notified_peers": notified_peers,
    }


@app.post("/revalidate/{object_id}", response_model=InvalidateResponse)
async def revalidate(object_id: str, auth: AuthContext = Depends(require_auth)):
    # The coordinator does not fetch content itself. Revalidation means clearing
    # stale discovery/cache state so the next requester refetches from origin.
    return await invalidate(object_id, auth)


@app.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    responses={404: {"model": ErrorResponse}},
)
async def heartbeat(req: HeartbeatRequest, auth: AuthContext = Depends(require_auth)):
    _enforce_peer_id_match(auth.peer_id, req.peer_id)
    store.heartbeat(req.peer_id)
    return HeartbeatResponse(status="ok", peer_id=req.peer_id)


@app.post(
    "/report-transfer",
    response_model=TransferReportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def report_transfer(req: TransferReportRequest, auth: AuthContext = Depends(require_auth)):
    _enforce_peer_id_match(auth.peer_id, req.peer_id)
    load = store.report_transfer(req.peer_id, req.object_id, req.bytes_served)
    log_event(
        logger,
        logging.INFO,
        "transfer_reported",
        peer_id=req.peer_id,
        object_id=req.object_id,
        bytes_served=req.bytes_served,
        total_upload_requests=load.total_upload_requests,
        total_upload_bytes=load.total_upload_bytes,
    )
    return TransferReportResponse(
        status="ok",
        peer_id=req.peer_id,
        total_upload_requests=load.total_upload_requests,
        total_upload_bytes=load.total_upload_bytes,
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service=settings.service_name)


@app.post("/report-bad-peer", response_model=BadPeerReportResponse)
async def report_bad_peer(
    req: BadPeerReportRequest, auth: AuthContext = Depends(require_auth)
):
    """Workstream 3: a peer reports another peer for misbehavior.

    Reporter identity is taken from `request.state.auth.peer_id` (set by the
    require_auth dependency), NOT the body — peers cannot launder reports
    through someone else's name. The body carries the accused.

    Returns 404-shaped state when reputation is disabled or the report was
    dropped (self-report, dedupe, exempt origin, unknown reason).
    """
    rep = reputation_tracker.record_incident(
        accused_peer_id=req.accused_peer_id,
        reason=req.reason,
        reporter_peer_id=auth.peer_id,
        object_id=req.object_id,
    )
    if rep is None:
        # Either reputation disabled, exempt peer, self-report, or rate-limited.
        # Return a synthetic snapshot so the caller can branch on the response
        # without parsing different shapes.
        snapshot = PeerReputationSnapshot(
            peer_id=req.accused_peer_id, state="healthy", score=0.0,
        )
        return BadPeerReportResponse(
            status="ignored", accused_peer_id=req.accused_peer_id, snapshot=snapshot,
        )

    log_event(
        logger, logging.WARNING, "bad_peer_reported",
        reporter=auth.peer_id, accused=req.accused_peer_id,
        reason=req.reason, object_id=req.object_id,
        new_state=rep.state, score=rep.score,
    )
    return BadPeerReportResponse(
        status="recorded",
        accused_peer_id=req.accused_peer_id,
        snapshot=PeerReputationSnapshot(**rep.to_dict()),
    )


@app.get("/stats", response_model=CoordinatorStatsResponse)
async def stats(_: AuthContext = Depends(require_auth)):
    data = store.get_stats()
    reputation_snapshots = []
    if settings.reputation.enabled:
        reputation_snapshots = [
            PeerReputationSnapshot(**rep.to_dict())
            for rep in reputation_tracker.snapshots()
        ]
    return CoordinatorStatsResponse(
        status="ok",
        service=settings.service_name,
        peer_count=data["peer_count"],
        object_count=data["object_count"],
        provider_entries=data["provider_entries"],
        max_providers_per_lookup=data["max_providers_per_lookup"],
        peer_timeout_seconds=settings.peer_timeout_seconds,
        provider_selection_policy=data["provider_selection_policy"],
        total_upload_requests=data["total_upload_requests"],
        total_upload_bytes=data["total_upload_bytes"],
        peer_loads=data["peer_loads"],
        peer_reputations=reputation_snapshots,
    )
