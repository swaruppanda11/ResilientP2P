import httpx
import time
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional

from common.config import get_peer_settings
from common.logging import get_logger, log_event
from common.schemas import (
    HeartbeatRequest,
    LookupResponse,
    ObjectMetadata,
    PublishRequest,
    RegisterRequest,
    TransferReportRequest,
)
from common.metrics import log_metric, MetricEvent
from peer.cache import Cache, CacheWriteResult


@dataclass(frozen=True)
class FetchResult:
    object_id: str
    source: str
    size: int
    latency_ms: float
    candidate_count: int = 0
    provider: Optional[str] = None
    data: Optional[bytes] = None


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
        self.host = self.settings.host
        self.port = self.settings.port
        self._register_lock = asyncio.Lock()

    async def register(self, host: str, port: int):
        self.host = host
        self.port = port
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await self._re_register_with_coordinator(reason="heartbeat_unknown_peer")
                return
            log_event(
                self.logger,
                logging.ERROR,
                "peer_heartbeat_failed",
                peer_id=self.peer_id,
                error=str(e),
            )
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "peer_heartbeat_failed",
                peer_id=self.peer_id,
                error=str(e),
            )

    async def fetch_object(self, object_id: str) -> Optional[FetchResult]:
        start_time = time.perf_counter()

        # 1. Check local cache
        cached_data = self.cache.get(object_id)
        if cached_data is not None:
            log_event(
                self.logger,
                logging.INFO,
                "cache_hit",
                peer_id=self.peer_id,
                object_id=object_id,
            )
            cache_stats = self.cache.get_stats()
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="CACHE_HIT",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
                bytes_transferred=len(cached_data),
                provider_peer=self.peer_id,
                cache_capacity_bytes=cache_stats["capacity_bytes"],
                cache_size_bytes=cache_stats["current_size_bytes"],
                cache_object_count=cache_stats["object_count"],
            ))
            return FetchResult(
                object_id=object_id,
                source="cache",
                size=len(cached_data),
                latency_ms=(time.perf_counter() - start_time) * 1000,
                candidate_count=0,
                provider=self.peer_id,
                data=cached_data,
            )

        log_metric(MetricEvent(
            source_peer=self.peer_id,
            event_type="CACHE_MISS",
            object_id=object_id,
            latency_ms=(time.perf_counter() - start_time) * 1000,
            location_id=self.location_id,
        ))

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
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="LOOKUP_RESULT",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
                candidate_count=len(providers),
            ))
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "lookup_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(e),
            )
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="LOOKUP_FAILURE",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
            ))

        # 3. Try Peers
        for peer_url in providers:
            try:
                # Assuming peer has /get-object/{id} endpoint
                p_resp = await self.http_client.get(
                    f"{peer_url}/get-object/{object_id}",
                    params={"requester_location_id": self.location_id},
                    timeout=self.settings.lookup_timeout_seconds,
                )
                p_resp.raise_for_status()
                data_hex = p_resp.json()["content_hex"]
                data = bytes.fromhex(data_hex)
                
                # Store in cache and publish
                if metadata:
                    write_result = self.cache.put(metadata, data)
                    self._log_cache_write_metrics(object_id, write_result)
                    if write_result.stored:
                        await self.publish(metadata)
                    
                latency = (time.perf_counter() - start_time) * 1000
                log_metric(MetricEvent(
                    source_peer=self.peer_id,
                    event_type="PEER_FETCH",
                    object_id=object_id,
                    latency_ms=latency,
                    location_id=self.location_id,
                    bytes_transferred=len(data),
                    provider_peer=peer_url,
                    candidate_count=len(providers),
                ))
                return FetchResult(
                    object_id=object_id,
                    source="peer",
                    size=len(data),
                    latency_ms=latency,
                    candidate_count=len(providers),
                    provider=peer_url,
                    data=data,
                )
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
            write_result = self.cache.put(meta, data)
            self._log_cache_write_metrics(object_id, write_result)
            if write_result.stored:
                await self.publish(meta)

            latency = (time.perf_counter() - start_time) * 1000
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="ORIGIN_FETCH",
                object_id=object_id,
                latency_ms=latency,
                location_id=self.location_id,
                bytes_transferred=len(data),
                provider_peer=self.origin_url,
            ))
            return FetchResult(
                object_id=object_id,
                source="origin",
                size=len(data),
                latency_ms=latency,
                candidate_count=len(providers),
                provider=self.origin_url,
                data=data,
            )
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await self._re_register_with_coordinator(reason="publish_unknown_peer")
                retry_resp = await self.http_client.post(f"{self.coordinator_url}/publish", json=req.dict())
                retry_resp.raise_for_status()
                return
            log_event(
                self.logger,
                logging.ERROR,
                "publish_failed",
                peer_id=self.peer_id,
                object_id=metadata.object_id,
                error=str(e),
            )
        except Exception as e:
            log_event(
                self.logger,
                logging.ERROR,
                "publish_failed",
                peer_id=self.peer_id,
                object_id=metadata.object_id,
                error=str(e),
            )

    async def report_transfer(self, object_id: str, bytes_served: int) -> None:
        req = TransferReportRequest(
            peer_id=self.peer_id,
            object_id=object_id,
            bytes_served=bytes_served,
        )
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/report-transfer",
                json=req.dict(),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await self._re_register_with_coordinator(reason="transfer_report_unknown_peer")
                retry_resp = await self.http_client.post(
                    f"{self.coordinator_url}/report-transfer",
                    json=req.dict(),
                )
                retry_resp.raise_for_status()
                return
            log_event(
                self.logger,
                logging.WARNING,
                "transfer_report_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                bytes_served=bytes_served,
                error=str(e),
            )
        except Exception as e:
            log_event(
                self.logger,
                logging.WARNING,
                "transfer_report_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                bytes_served=bytes_served,
                error=str(e),
            )

    def _log_cache_write_metrics(self, object_id: str, write_result: CacheWriteResult) -> None:
        cache_stats = self.cache.get_stats()
        event_type = "CACHE_STORE" if write_result.stored else "CACHE_REJECTED"
        log_metric(MetricEvent(
            source_peer=self.peer_id,
            event_type=event_type,
            object_id=object_id,
            latency_ms=0.0,
            location_id=self.location_id,
            bytes_transferred=write_result.object_size_bytes if write_result.stored else 0,
            evicted_bytes=write_result.evicted_bytes,
            evicted_count=len(write_result.evicted_object_ids),
            cache_capacity_bytes=cache_stats["capacity_bytes"],
            cache_size_bytes=cache_stats["current_size_bytes"],
            cache_object_count=cache_stats["object_count"],
        ))

    async def _re_register_with_coordinator(self, reason: str) -> None:
        async with self._register_lock:
            log_event(
                self.logger,
                logging.WARNING,
                "peer_re_registering",
                peer_id=self.peer_id,
                reason=reason,
            )
            await self.register(self.host, self.port)
            for metadata in self.cache.metadata.values():
                try:
                    req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
                    resp = await self.http_client.post(
                        f"{self.coordinator_url}/publish",
                        json=req.dict(),
                    )
                    resp.raise_for_status()
                except Exception as e:
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "peer_republish_failed",
                        peer_id=self.peer_id,
                        object_id=metadata.object_id,
                        error=str(e),
                    )
