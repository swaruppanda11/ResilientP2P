import httpx
import time
import asyncio
from typing import Optional, List
from common.schemas import ObjectMetadata, RegisterRequest, PublishRequest, LookupResponse, HeartbeatRequest
from common.metrics import log_metric, MetricEvent
from peer.cache import Cache

class PeerClient:
    def __init__(self, peer_id: str, location_id: str, coordinator_url: str, origin_url: str, cache: Cache):
        self.peer_id = peer_id
        self.location_id = location_id
        self.coordinator_url = coordinator_url
        self.origin_url = origin_url
        self.cache = cache
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def register(self, host: str, port: int):
        req = RegisterRequest(
            peer_id=self.peer_id,
            host=host,
            port=port,
            location_id=self.location_id
        )
        try:
            await self.http_client.post(f"{self.coordinator_url}/register", json=req.dict())
            print(f"Registered peer {self.peer_id}")
        except Exception as e:
            print(f"Registration failed: {e}")

    async def heartbeat(self):
        req = HeartbeatRequest(peer_id=self.peer_id)
        try:
            await self.http_client.post(f"{self.coordinator_url}/heartbeat", json=req.dict())
        except Exception as e:
            print(f"Heartbeat failed: {e}")

    async def fetch_object(self, object_id: str) -> Optional[bytes]:
        # 1. Check local cache
        if self.cache.has(object_id):
            return self.cache.get(object_id)

        start_time = time.time()

        # 2. Lookup in Coordinator
        providers = []
        metadata = None
        try:
            resp = await self.http_client.get(
                f"{self.coordinator_url}/lookup/{object_id}", 
                params={"location_id": self.location_id}
            )
            if resp.status_code == 200:
                lookup = LookupResponse(**resp.json())
                providers = lookup.providers
                metadata = lookup.metadata
        except Exception as e:
            print(f"Lookup failed: {e}")

        # 3. Try Peers
        for peer_url in providers:
            try:
                p_start = time.time()
                # Assuming peer has /get-object/{id} endpoint
                # Faster 2s timeout for P2P fetches
                p_resp = await self.http_client.get(f"{peer_url}/get-object/{object_id}", timeout=2.0)
                if p_resp.status_code == 200:
                    data_hex = p_resp.json()["content_hex"]
                    data = bytes.fromhex(data_hex)
                    
                    # Store in cache and publish
                    if metadata:
                        self.cache.put(metadata, data)
                        await self.publish(metadata)
                        
                        latency = (time.time() - start_time) * 1000
                        log_metric(MetricEvent(
                            source_peer=self.peer_id,
                            event_type="PEER_FETCH",
                            object_id=object_id,
                            latency_ms=latency,
                            location_id=self.location_id
                        ))
                        return data
            except Exception as e:
                print(f"Fetch from peer {peer_url} failed: {e}")
                continue

        # 4. Fallback to Origin
        try:
            o_start = time.time()
            o_resp = await self.http_client.get(f"{self.origin_url}/object/{object_id}")
            if o_resp.status_code == 200:
                res = o_resp.json()
                data = bytes.fromhex(res["content_hex"]) 
                meta = ObjectMetadata(
                    object_id=object_id,
                    checksum=res["checksum"],
                    size_bytes=res["size"]
                )
                self.cache.put(meta, data)
                await self.publish(meta)

                latency = (time.time() - start_time) * 1000
                log_metric(MetricEvent(
                    source_peer=self.peer_id,
                    event_type="ORIGIN_FETCH",
                    object_id=object_id,
                    latency_ms=latency,
                    location_id=self.location_id
                ))
                return data
        except Exception as e:
            print(f"Origin fetch failed: {e}")

        return None

    async def publish(self, metadata: ObjectMetadata):
        req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
        try:
            await self.http_client.post(f"{self.coordinator_url}/publish", json=req.dict())
        except Exception as e:
            print(f"Publish failed: {e}")
