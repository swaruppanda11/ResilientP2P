from fastapi import FastAPI, HTTPException
import os
import asyncio
import socket
from peer.cache import Cache
from peer.client import PeerClient
from contextlib import asynccontextmanager

# Config from Env
PEER_ID = os.getenv("PEER_ID", f"peer-{socket.gethostname()}")
LOCATION_ID = os.getenv("LOCATION_ID", "Building-A")
COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://coordinator:8000")
ORIGIN_URL = os.getenv("ORIGIN_URL", "http://origin:8001")
HOST = PEER_ID
PORT = 7000

cache = Cache()
client = PeerClient(PEER_ID, LOCATION_ID, COORDINATOR_URL, ORIGIN_URL, cache)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Register with coordinator
    await client.register(HOST, PORT)
    
    # 2. Start heartbeat loop
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    
    yield
    heartbeat_task.cancel()

async def heartbeat_loop():
    while True:
        await client.heartbeat()
        await asyncio.sleep(10)

app = FastAPI(title=f"Peer {PEER_ID}", lifespan=lifespan)

@app.get("/get-object/{object_id}")
async def get_object(object_id: str):
    data = cache.get(object_id)
    if not data:
        raise HTTPException(status_code=404, detail="Object not in cache")
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
