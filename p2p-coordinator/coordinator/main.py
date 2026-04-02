import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from common.config import get_coordinator_settings
from common.logging import get_logger, log_event
from common.schemas import (
    CoordinatorStatsResponse,
    ErrorResponse,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LookupResponse,
    PublishRequest,
    PublishResponse,
    RegisterRequest,
    RegisterResponse,
    TransferReportRequest,
    TransferReportResponse,
)
from coordinator.store import (
    DuplicatePeerError,
    InvalidPublishError,
    Store,
    UnknownPeerError,
)
import asyncio

settings = get_coordinator_settings()
logger = get_logger(settings.service_name)
store = Store(
    max_providers_per_lookup=settings.max_providers_per_lookup,
    provider_selection_policy=settings.provider_selection_policy,
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


@app.post(
    "/register",
    response_model=RegisterResponse,
    responses={409: {"model": ErrorResponse}},
)
async def register(req: RegisterRequest):
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
async def publish(req: PublishRequest):
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
async def lookup(object_id: str, location_id: str = Query(...)):
    providers = store.get_providers(object_id, location_id)
    metadata = store.object_metadata.get(object_id)
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

@app.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    responses={404: {"model": ErrorResponse}},
)
async def heartbeat(req: HeartbeatRequest):
    store.heartbeat(req.peer_id)
    return HeartbeatResponse(status="ok", peer_id=req.peer_id)


@app.post(
    "/report-transfer",
    response_model=TransferReportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def report_transfer(req: TransferReportRequest):
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


@app.get("/stats", response_model=CoordinatorStatsResponse)
async def stats():
    data = store.get_stats()
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
    )
