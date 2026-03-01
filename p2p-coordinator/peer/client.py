import httpx
import time
import logging
from typing import Optional
from common.config import get_peer_settings
from common.logging import get_logger, log_event
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
        self.settings = get_peer_settings()
        self.logger = get_logger(f"{self.settings.service_name}:{self.peer_id}")
        self.http_client = httpx.AsyncClient(timeout=10.0)

    async def register(self, host: str, port: int):
        req = RegisterRequest(
            peer_id=self.peer_id,
            host=host,
            port=port,
            location_id=self.location_id
        )
        try:
            resp = await self.http_client.post(f"{self.coordinator_url}/register", json=req.dict())
            resp.raise_for_status()
            log_event(self.logger, logging.INFO, "peer_register_success", peer_id=self.peer_id)
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "peer_register_failed",
                peer_id=self.peer_id,
                error=str(e),
            )

    async def heartbeat(self):
        req = HeartbeatRequest(peer_id=self.peer_id)
        try:
            resp = await self.http_client.post(f"{self.coordinator_url}/heartbeat", json=req.dict())
            resp.raise_for_status()
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "peer_heartbeat_failed",
                peer_id=self.peer_id,
                error=str(e),
            )

    async def fetch_object(self, object_id: str) -> Optional[bytes]:
        # 1. Check local cache
        if self.cache.has(object_id):
            log_event(
                self.logger,
                logging.INFO,
                "cache_hit",
                peer_id=self.peer_id,
                object_id=object_id,
            )
            return self.cache.get(object_id)

        start_time = time.time()

        # 2. Lookup in Coordinator
        providers = []
        metadata = None
        try:
            resp = await self.http_client.get(
                f"{self.coordinator_url}/lookup/{object_id}", 
                params={"location_id": self.location_id},
                timeout=self.settings.lookup_timeout_seconds,
            )
            resp.raise_for_status()
            lookup = LookupResponse(**resp.json())
            providers = lookup.providers
            metadata = lookup.metadata
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "lookup_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(e),
            )

        # 3. Try Peers
        for peer_url in providers:
            try:
                # Assuming peer has /get-object/{id} endpoint
                p_resp = await self.http_client.get(
                    f"{peer_url}/get-object/{object_id}",
                    timeout=self.settings.lookup_timeout_seconds,
                )
                p_resp.raise_for_status()
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
                log_event(
                    self.logger,
                    logging.WARNING,
                    "peer_fetch_failed",
                    peer_id=self.peer_id,
                    object_id=object_id,
                    provider=peer_url,
                    error=str(e),
                )
                continue

        # 4. Fallback to Origin
        try:
            o_resp = await self.http_client.get(f"{self.origin_url}/object/{object_id}")
            o_resp.raise_for_status()
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
            log_event(
                self.logger,
                logging.ERROR,
                "origin_fetch_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(e),
            )

        return None

    async def publish(self, metadata: ObjectMetadata):
        req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
        try:
            resp = await self.http_client.post(f"{self.coordinator_url}/publish", json=req.dict())
            resp.raise_for_status()
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "publish_failed",
                peer_id=self.peer_id,
                object_id=metadata.object_id,
                error=str(e),
            )
