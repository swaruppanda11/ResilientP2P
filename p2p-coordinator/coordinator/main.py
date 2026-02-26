from fastapi import FastAPI, BackgroundTasks, Query
from common.schemas import RegisterRequest, PublishRequest, LookupResponse, HeartbeatRequest
from coordinator.store import Store
import asyncio
from contextlib import asynccontextmanager

store = Store()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    yield
    cleanup_task.cancel()

async def periodic_cleanup():
    while True:
        await asyncio.sleep(10)
        store.cleanup(timeout_seconds=30)

app = FastAPI(title="P2P Coordinator", lifespan=lifespan)

@app.post("/register")
async def register(req: RegisterRequest):
    peer = store.register_peer(req)
    return {"status": "registered", "peer_id": peer.peer_id}

@app.post("/publish")
async def publish(req: PublishRequest):
    store.publish_object(req.peer_id, req.metadata)
    return {"status": "published"}

@app.get("/lookup/{object_id}", response_model=LookupResponse)
async def lookup(object_id: str, location_id: str = Query(...)):
    providers = store.get_providers(object_id, location_id)
    metadata = store.object_metadata.get(object_id)
    return LookupResponse(
        object_id=object_id,
        providers=providers,
        metadata=metadata
    )

@app.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    store.heartbeat(req.peer_id)
    return {"status": "ok"}
