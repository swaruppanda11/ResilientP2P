"""
DHT-primary peer client.

Fetch order:
  1. Local cache hit                      → source="cache"
  2. DHT lookup  → peer fetch             → source="peer",  dht_used=True
  3. Coordinator fallback → peer fetch    → source="peer",  coordinator_fallback_used=True
  4. Origin fetch                         → source="origin"

The coordinator is also updated on every successful cache store so that the
Coordinator-primary experiments can serve as a meaningful comparison baseline:
both architectures share the same coordinator index, so cache hit rates
reflect discovery differences rather than content availability differences.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

from common.config import get_dht_peer_settings
from common.logging import get_logger, log_event
from common.metrics import MetricEvent, log_metric
from common.schemas import (
    HeartbeatRequest,
    LookupResponse,
    ObjectMetadata,
    PublishRequest,
    RegisterRequest,
    TransferReportRequest,
)
from dht.node import DHTNode
from peer.cache import Cache, CacheWriteResult


@dataclass(frozen=True)
class FetchResult:
    object_id: str
    source: str           # "cache" | "peer" | "origin"
    size: int
    latency_ms: float
    candidate_count: int = 0
    provider: Optional[str] = None
    data: Optional[bytes] = None
    dht_used: bool = False
    coordinator_fallback_used: bool = False


class DHTPeerClient:
    def __init__(
        self,
        peer_id: str,
        location_id: str,
        dht_node: DHTNode,
        coordinator_url: str,
        origin_url: str,
        cache: Cache,
    ):
        self.peer_id = peer_id
        self.location_id = location_id
        self.dht_node = dht_node
        self.coordinator_url = coordinator_url
        self.origin_url = origin_url
        self.cache = cache
        self.settings = get_dht_peer_settings()
        self.logger = get_logger(f"dht-peer:{peer_id}")
        self.http_client = httpx.AsyncClient(timeout=10.0)
        self.host = self.settings.host
        self.port = self.settings.port
        self._register_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def register(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        req = RegisterRequest(
            peer_id=self.peer_id, host=host, port=port, location_id=self.location_id
        )
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/register", json=req.dict()
            )
            resp.raise_for_status()
            log_event(
                self.logger, logging.INFO, "peer_register_success", peer_id=self.peer_id
            )
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "peer_register_failed",
                peer_id=self.peer_id,
                error=str(exc),
            )

    async def heartbeat(self) -> None:
        req = HeartbeatRequest(peer_id=self.peer_id)
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/heartbeat", json=req.dict()
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                await self._re_register(reason="heartbeat_unknown_peer")
                return
            log_event(
                self.logger,
                logging.ERROR,
                "heartbeat_failed",
                peer_id=self.peer_id,
                error=str(exc),
            )
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "heartbeat_failed",
                peer_id=self.peer_id,
                error=str(exc),
            )

    async def republish_all(self) -> None:
        """Re-announce all cached objects to the DHT (churn recovery)."""
        for object_id in list(self.cache.storage.keys()):
            await self._announce_dht(object_id)

    # ------------------------------------------------------------------
    # Core fetch pipeline
    # ------------------------------------------------------------------

    async def fetch_object(self, object_id: str) -> Optional[FetchResult]:
        start_time = time.perf_counter()

        # 1. Local cache hit
        cached_data = self.cache.get(object_id)
        if cached_data is not None:
            cache_stats = self.cache.get_stats()
            log_event(
                self.logger, logging.INFO, "cache_hit",
                peer_id=self.peer_id, object_id=object_id,
            )
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
                provider=self.peer_id,
                data=cached_data,
                dht_used=False,
            )

        log_metric(MetricEvent(
            source_peer=self.peer_id,
            event_type="CACHE_MISS",
            object_id=object_id,
            latency_ms=(time.perf_counter() - start_time) * 1000,
            location_id=self.location_id,
        ))

        # 2. DHT lookup (primary)
        dht_providers, dht_failed = await self._dht_lookup(object_id, start_time)

        # 3. Coordinator fallback when DHT fails or returns no providers
        coordinator_fallback_used = False
        metadata: Optional[ObjectMetadata] = None
        coord_urls: List[str] = []

        if dht_failed or not dht_providers:
            coord_urls, metadata = await self._coordinator_lookup(object_id, start_time)
            coordinator_fallback_used = True
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="COORDINATOR_FALLBACK",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
            ))

        # Build ordered candidate list: locality-sorted DHT peers first, then
        # coordinator peers (already sorted server-side).
        peer_urls = self._select_dht_providers(dht_providers) + coord_urls
        candidate_count = len(peer_urls)

        # 4. Try each candidate peer
        for peer_url in peer_urls:
            try:
                p_resp = await self.http_client.get(
                    f"{peer_url}/get-object/{object_id}",
                    params={"requester_location_id": self.location_id},
                    timeout=self.settings.lookup_timeout_seconds,
                )
                p_resp.raise_for_status()
                data = bytes.fromhex(p_resp.json()["content_hex"])

                if metadata is None:
                    metadata = self.cache.get_metadata(object_id)
                if metadata:
                    write_result = self.cache.put(metadata, data)
                    self._log_cache_write(object_id, write_result)
                    if write_result.stored:
                        self._schedule_post_store_updates(metadata)

                latency = (time.perf_counter() - start_time) * 1000
                log_metric(MetricEvent(
                    source_peer=self.peer_id,
                    event_type="PEER_FETCH",
                    object_id=object_id,
                    latency_ms=latency,
                    location_id=self.location_id,
                    bytes_transferred=len(data),
                    provider_peer=peer_url,
                    candidate_count=candidate_count,
                ))
                return FetchResult(
                    object_id=object_id,
                    source="peer",
                    size=len(data),
                    latency_ms=latency,
                    candidate_count=candidate_count,
                    provider=peer_url,
                    data=data,
                    dht_used=not dht_failed,
                    coordinator_fallback_used=coordinator_fallback_used,
                )
            except Exception as exc:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "peer_fetch_failed",
                    peer_id=self.peer_id,
                    object_id=object_id,
                    provider=peer_url,
                    error=str(exc),
                )

        # 5. Origin fallback
        try:
            o_resp = await self.http_client.get(f"{self.origin_url}/object/{object_id}")
            o_resp.raise_for_status()
            res = o_resp.json()
            data = bytes.fromhex(res["content_hex"])
            metadata = ObjectMetadata(
                object_id=object_id,
                checksum=res["checksum"],
                size_bytes=res["size"],
            )
            write_result = self.cache.put(metadata, data)
            self._log_cache_write(object_id, write_result)
            if write_result.stored:
                self._schedule_post_store_updates(metadata)

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
                candidate_count=candidate_count,
                provider=self.origin_url,
                data=data,
                coordinator_fallback_used=coordinator_fallback_used,
            )
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "origin_fetch_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(exc),
            )

        return None

    async def report_transfer(self, object_id: str, bytes_served: int) -> None:
        req = TransferReportRequest(
            peer_id=self.peer_id, object_id=object_id, bytes_served=bytes_served
        )
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/report-transfer", json=req.dict()
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                await self._re_register(reason="transfer_report_unknown_peer")
                retry = await self.http_client.post(
                    f"{self.coordinator_url}/report-transfer", json=req.dict()
                )
                retry.raise_for_status()
                return
            log_event(
                self.logger,
                logging.WARNING,
                "transfer_report_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(exc),
            )
        except Exception as exc:
            log_event(
                self.logger,
                logging.WARNING,
                "transfer_report_failed",
                peer_id=self.peer_id,
                object_id=object_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _dht_lookup(
        self, object_id: str, start_time: float
    ) -> Tuple[List[Dict], bool]:
        """
        Perform a DHT lookup with a per-request timeout.

        Returns (providers, failed). 'failed' is True when the DHT timed out
        or raised an unexpected error, indicating coordinator fallback is needed.
        """
        try:
            providers = await asyncio.wait_for(
                self.dht_node.lookup(object_id),
                timeout=self.settings.dht_lookup_timeout_seconds,
            )
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="DHT_LOOKUP_RESULT",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
                candidate_count=len(providers),
            ))
            log_event(
                self.logger, logging.INFO, "dht_lookup_success",
                peer_id=self.peer_id, object_id=object_id,
                provider_count=len(providers),
            )
            return providers, False
        except asyncio.TimeoutError:
            log_event(
                self.logger, logging.WARNING, "dht_lookup_timeout",
                peer_id=self.peer_id, object_id=object_id,
            )
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="DHT_LOOKUP_TIMEOUT",
                object_id=object_id,
                latency_ms=self.settings.dht_lookup_timeout_seconds * 1000,
                location_id=self.location_id,
            ))
            return [], True
        except Exception as exc:
            log_event(
                self.logger, logging.ERROR, "dht_lookup_error",
                peer_id=self.peer_id, object_id=object_id, error=str(exc),
            )
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="DHT_LOOKUP_FAILURE",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
            ))
            return [], True

    async def _coordinator_lookup(
        self, object_id: str, start_time: float
    ) -> Tuple[List[str], Optional[ObjectMetadata]]:
        """Query the coordinator for providers (fallback path)."""
        try:
            resp = await self.http_client.get(
                f"{self.coordinator_url}/lookup/{object_id}",
                params={"location_id": self.location_id},
                timeout=self.settings.lookup_timeout_seconds,
            )
            resp.raise_for_status()
            lookup = LookupResponse(**resp.json())
            log_metric(MetricEvent(
                source_peer=self.peer_id,
                event_type="COORDINATOR_LOOKUP_RESULT",
                object_id=object_id,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                location_id=self.location_id,
                candidate_count=len(lookup.providers),
            ))
            return lookup.providers, lookup.metadata
        except Exception as exc:
            log_event(
                self.logger, logging.ERROR, "coordinator_lookup_failed",
                peer_id=self.peer_id, object_id=object_id, error=str(exc),
            )
            return [], None

    def _select_dht_providers(self, dht_providers: List[Dict]) -> List[str]:
        """
        Sort DHT provider list by locality (same building first) and return
        up to max_providers_per_lookup URLs, excluding self.
        """
        filtered = [p for p in dht_providers if p.get("peer_id") != self.peer_id]
        sorted_providers = sorted(
            filtered,
            key=lambda p: (p.get("location_id") != self.location_id, p.get("peer_id", "")),
        )
        return [p["url"] for p in sorted_providers[: self.settings.max_providers_per_lookup]]

    async def _announce_dht(self, object_id: str) -> None:
        peer_url = f"http://{self.host}:{self.port}"
        announced = await self.dht_node.announce_with_retry(
            object_id=object_id,
            peer_id=self.peer_id,
            peer_url=peer_url,
            location_id=self.location_id,
        )
        if not announced:
            log_event(
                self.logger,
                logging.WARNING,
                "dht_announce_failed_after_retries",
                peer_id=self.peer_id,
                object_id=object_id,
            )

    def _schedule_post_store_updates(self, metadata: ObjectMetadata) -> None:
        asyncio.create_task(self._post_store_updates(metadata))

    async def _post_store_updates(self, metadata: ObjectMetadata) -> None:
        await self._announce_dht(metadata.object_id)
        await self._publish_coordinator(metadata)

    async def _publish_coordinator(self, metadata: ObjectMetadata) -> None:
        """Keep the coordinator index up-to-date for fallback lookups."""
        req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/publish", json=req.dict()
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                await self._re_register(reason="publish_unknown_peer")
                retry = await self.http_client.post(
                    f"{self.coordinator_url}/publish", json=req.dict()
                )
                retry.raise_for_status()
                return
            log_event(
                self.logger, logging.ERROR, "publish_failed",
                peer_id=self.peer_id, object_id=metadata.object_id, error=str(exc),
            )
        except Exception as exc:
            log_event(
                self.logger, logging.ERROR, "publish_failed",
                peer_id=self.peer_id, object_id=metadata.object_id, error=str(exc),
            )

    def _log_cache_write(self, object_id: str, result: CacheWriteResult) -> None:
        cache_stats = self.cache.get_stats()
        log_metric(MetricEvent(
            source_peer=self.peer_id,
            event_type="CACHE_STORE" if result.stored else "CACHE_REJECTED",
            object_id=object_id,
            latency_ms=0.0,
            location_id=self.location_id,
            bytes_transferred=result.object_size_bytes if result.stored else 0,
            evicted_bytes=result.evicted_bytes,
            evicted_count=len(result.evicted_object_ids),
            cache_capacity_bytes=cache_stats["capacity_bytes"],
            cache_size_bytes=cache_stats["current_size_bytes"],
            cache_object_count=cache_stats["object_count"],
        ))

    async def _re_register(self, reason: str) -> None:
        async with self._register_lock:
            log_event(
                self.logger, logging.WARNING, "peer_re_registering",
                peer_id=self.peer_id, reason=reason,
            )
            await self.register(self.host, self.port)
            for metadata in self.cache.metadata.values():
                try:
                    req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
                    resp = await self.http_client.post(
                        f"{self.coordinator_url}/publish", json=req.dict()
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    log_event(
                        self.logger, logging.WARNING, "peer_republish_failed",
                        peer_id=self.peer_id,
                        object_id=metadata.object_id,
                        error=str(exc),
                    )
