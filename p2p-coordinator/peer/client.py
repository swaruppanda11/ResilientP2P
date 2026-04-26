"""
Coordinator-primary peer client.

Fetch order:
  1. Local cache hit                      → source="cache"
  2. Coordinator lookup → peer fetch      → source="peer",  coordinator_used=True
  3. DHT fallback → peer fetch            → source="peer",  dht_fallback_used=True
  4. Origin fetch                         → source="origin"

The DHT is also updated on every successful cache store so that the
DHT-primary experiments can serve as a meaningful comparison baseline:
both architectures share the same DHT index, so cache hit rates
reflect discovery differences rather than content availability differences.
"""

import asyncio
import hashlib
import json
import httpx
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from urllib.parse import urlparse

from common.auth import outbound_auth
from common.config import get_peer_settings
from common.logging import get_logger, log_event
from common.schemas import (
    BadPeerReportRequest,
    HeartbeatRequest,
    LookupResponse,
    ObjectMetadata,
    PublishRequest,
    RegisterRequest,
    TransferReportRequest,
)


def _peer_id_from_url(url: str) -> str:
    """Best-effort peer_id extraction from a peer URL.

    Works for both K8s (`peer-a1.p2p-coordinator.svc.cluster.local:7000`)
    and docker-compose (`peer-a1:7000`) URL shapes — the first hostname
    segment is the service / container name and matches the peer_id.
    """
    host = urlparse(url).hostname or ""
    return host.split(".")[0]
from common.metrics import log_metric, MetricEvent
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
    coordinator_used: bool = False
    dht_fallback_used: bool = False


class PeerClient:
    def __init__(
        self,
        peer_id: str,
        location_id: str,
        coordinator_url: str,
        origin_url: str,
        cache: Cache,
        dht_node: DHTNode,
    ):
        self.peer_id = peer_id
        self.location_id = location_id
        self.coordinator_url = coordinator_url
        self.origin_url = origin_url
        self.cache = cache
        self.dht_node = dht_node
        self.settings = get_peer_settings()
        self.logger = get_logger(f"{self.settings.service_name}:{self.peer_id}")
        self.http_client = httpx.AsyncClient(
            timeout=10.0,
            auth=outbound_auth(peer_id=self.peer_id),
        )
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

    async def republish_all(self) -> None:
        """Re-announce all cached objects to the DHT (churn recovery)."""
        for object_id in list(self.cache.storage.keys()):
            metadata = self.cache.get_metadata(object_id)
            if metadata is not None:
                await self._announce_dht(metadata)

    # ------------------------------------------------------------------
    # Core fetch pipeline
    # ------------------------------------------------------------------

    async def fetch_object(
        self,
        object_id: str,
        version: Optional[str] = None,
        cacheability: Optional[str] = None,
        max_age_seconds: Optional[int] = None,
    ) -> Optional[FetchResult]:
        start_time = time.perf_counter()

        # 1. Check local cache
        if version:
            cached_metadata = self.cache.get_metadata(object_id)
            if cached_metadata is not None and cached_metadata.version != version:
                self.cache.invalidate(object_id)
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

        # 2. Coordinator lookup (primary)
        providers: List[str] = []
        metadata: Optional[ObjectMetadata] = None
        coordinator_failed = False
        try:
            resp = await self.http_client.get(
                f"{self.coordinator_url}/lookup/{object_id}",
                params={
                    "location_id": self.location_id,
                    **({"version": version} if version else {}),
                },
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
            coordinator_failed = True
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

        # 3. DHT fallback when coordinator fails or returns no providers
        dht_fallback_used = False
        dht_urls: List[str] = []

        if coordinator_failed or not providers:
            dht_providers, dht_failed = await self._dht_lookup(object_id, start_time, version)
            if not dht_failed and dht_providers:
                dht_fallback_used = True
                dht_urls = self._select_dht_providers(dht_providers)
                log_metric(MetricEvent(
                    source_peer=self.peer_id,
                    event_type="DHT_FALLBACK",
                    object_id=object_id,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                    location_id=self.location_id,
                    candidate_count=len(dht_urls),
                ))

        # Build ordered candidate list: coordinator peers first, then DHT peers
        peer_urls = providers + dht_urls
        candidate_count = len(peer_urls)

        # 4. Try Peers
        for peer_url in peer_urls:
            try:
                p_resp = await self.http_client.get(
                    f"{peer_url}/get-object/{object_id}",
                    params={"requester_location_id": self.location_id},
                    timeout=self.settings.lookup_timeout_seconds,
                )
                p_resp.raise_for_status()
                peer_payload = p_resp.json()
                data_hex = peer_payload["content_hex"]
                data = bytes.fromhex(data_hex)

                # Store in cache and publish
                if metadata is None:
                    peer_metadata = peer_payload.get("metadata")
                    if peer_metadata:
                        metadata = ObjectMetadata(**peer_metadata)
                    else:
                        metadata = self.cache.get_metadata(object_id)
                if version and metadata and metadata.version != version:
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "peer_fetch_version_mismatch",
                        peer_id=self.peer_id,
                        object_id=object_id,
                        expected_version=version,
                        provider=peer_url,
                        provider_version=metadata.version,
                    )
                    metadata = None
                    continue
                if metadata and hashlib.sha256(data).hexdigest() != metadata.checksum:
                    actual_checksum = hashlib.sha256(data).hexdigest()
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "peer_fetch_checksum_mismatch",
                        peer_id=self.peer_id,
                        object_id=object_id,
                        provider=peer_url,
                    )
                    # WS3: report the malicious provider, fire-and-forget.
                    asyncio.create_task(self.report_bad_peer(
                        accused_peer_id=_peer_id_from_url(peer_url),
                        object_id=object_id,
                        reason="checksum_mismatch",
                        expected_checksum=metadata.checksum,
                        actual_checksum=actual_checksum,
                        provider_url=peer_url,
                    ))
                    metadata = None
                    continue
                if metadata:
                    write_result = self.cache.put(metadata, data)
                    self._log_cache_write_metrics(object_id, write_result)
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
                    coordinator_used=not coordinator_failed,
                    dht_fallback_used=dht_fallback_used,
                )
            except httpx.HTTPStatusError as e:
                # WS3: a 404 from a peer that just claimed (via coordinator
                # lookup) to have this object is the "advertise_missing"
                # signal. 5xx is the same idea — peer says it has it but
                # can't deliver. Connection-level failures fall through to
                # the generic Exception handler and are NOT reported.
                if e.response.status_code in (404, 410, 500, 503):
                    asyncio.create_task(self.report_bad_peer(
                        accused_peer_id=_peer_id_from_url(peer_url),
                        object_id=object_id,
                        reason="unavailable",
                        provider_url=peer_url,
                    ))
                log_event(
                    self.logger,
                    logging.WARNING,
                    "peer_fetch_failed",
                    peer_id=self.peer_id,
                    object_id=object_id,
                    provider=peer_url,
                    status_code=e.response.status_code,
                    error=str(e),
                )
                continue
            except Exception as e:
                # Connection refused, timeout, DNS, etc. — transient, NOT
                # malicious behavior. Skip reporting.
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

        # 5. Fallback to Origin
        try:
            origin_params = {
                **({"version": version} if version else {}),
                **({"cacheability": cacheability} if cacheability else {}),
                **({"max_age_seconds": max_age_seconds} if max_age_seconds is not None else {}),
            }
            o_resp = await self.http_client.get(
                f"{self.origin_url}/object/{object_id}",
                params=origin_params,
            )
            o_resp.raise_for_status()
            res = o_resp.json()
            data = bytes.fromhex(res["content_hex"])
            meta = ObjectMetadata(
                object_id=object_id,
                checksum=res["checksum"],
                size_bytes=res["size"],
                version=res.get("version", "1"),
                cacheability=res.get("cacheability", "immutable"),
                max_age_seconds=res.get("max_age_seconds"),
                expires_at=res.get("expires_at"),
                etag=res.get("etag"),
            )
            # WS3: `advertise_missing` peers DO announce but do NOT cache —
            # the index claims they have it, /get-object on them then 404s.
            if self.settings.malicious_mode == "advertise_missing":
                log_event(
                    self.logger, logging.WARNING, "advertising_missing",
                    peer_id=self.peer_id, object_id=object_id,
                )
                self._schedule_post_store_updates(meta)
            else:
                write_result = self.cache.put(meta, data)
                self._log_cache_write_metrics(object_id, write_result)
                if write_result.stored:
                    self._schedule_post_store_updates(meta)

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
                dht_fallback_used=dht_fallback_used,
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _dht_lookup(
        self, object_id: str, start_time: float, version: Optional[str] = None
    ) -> Tuple[List[Dict], bool]:
        """
        Perform a DHT lookup with a per-request timeout.

        Returns (providers, failed). 'failed' is True when the DHT timed out
        or raised an unexpected error.
        """
        try:
            providers = await asyncio.wait_for(
                self.dht_node.lookup(object_id, version=version),
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

    async def _announce_dht(self, metadata: ObjectMetadata) -> None:
        """Announce cached object to DHT so the fallback index stays current."""
        peer_url = f"http://{self.host}:{self.port}"
        announced = await self.dht_node.announce_with_retry(
            object_id=metadata.object_id,
            peer_id=self.peer_id,
            peer_url=peer_url,
            location_id=self.location_id,
            version=metadata.version,
            cacheability=metadata.cacheability,
            expires_at=metadata.expires_at.isoformat() if metadata.expires_at else None,
            checksum=metadata.checksum,
        )
        if not announced:
            log_event(
                self.logger,
                logging.WARNING,
                "dht_announce_failed_after_retries",
                peer_id=self.peer_id,
                object_id=metadata.object_id,
            )

    def _schedule_post_store_updates(self, metadata: ObjectMetadata) -> None:
        asyncio.create_task(self._post_store_updates(metadata))

    async def _post_store_updates(self, metadata: ObjectMetadata) -> None:
        await self._announce_dht(metadata)
        await self.publish(metadata)

    async def publish(self, metadata: ObjectMetadata):
        # WS3: `publish_conflicting` mutates the checksum so the coordinator's
        # _metadata_conflicts detector raises against this peer (provided an
        # honest peer published the canonical metadata first).
        if self.settings.malicious_mode == "publish_conflicting":
            mutator = metadata.model_copy if hasattr(metadata, "model_copy") else metadata.copy
            metadata = mutator(update={"checksum": "0" * 64})
            log_event(
                self.logger, logging.WARNING, "publishing_conflicting_metadata",
                peer_id=self.peer_id, object_id=metadata.object_id,
            )
        req = PublishRequest(peer_id=self.peer_id, metadata=metadata)
        try:
            resp = await self.http_client.post(
                f"{self.coordinator_url}/publish",
                json=json.loads(req.json()),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await self._re_register_with_coordinator(reason="publish_unknown_peer")
                retry_resp = await self.http_client.post(
                    f"{self.coordinator_url}/publish",
                    json=json.loads(req.json()),
                )
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

    async def report_bad_peer(
        self,
        accused_peer_id: str,
        object_id: str,
        reason: str,
        expected_checksum: Optional[str] = None,
        actual_checksum: Optional[str] = None,
        provider_url: Optional[str] = None,
    ) -> None:
        """Workstream 3: tell the coordinator another peer misbehaved.

        Fire-and-forget; failures are logged but never bubble up — peer
        reputation reporting must never block the data plane.
        """
        if not self.settings.reputation.enabled:
            return
        if accused_peer_id == self.peer_id or not accused_peer_id:
            return
        try:
            req = BadPeerReportRequest(
                accused_peer_id=accused_peer_id,
                object_id=object_id,
                reason=reason,
                expected_checksum=expected_checksum,
                actual_checksum=actual_checksum,
                provider_url=provider_url,
            )
            await self.http_client.post(
                f"{self.coordinator_url}/report-bad-peer",
                json=req.dict(),
                timeout=2.0,
            )
        except Exception as exc:
            log_event(
                self.logger, logging.WARNING, "report_bad_peer_failed",
                peer_id=self.peer_id, accused=accused_peer_id,
                reason=reason, error=str(exc),
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
