"""
Kademlia DHT wrapper for content provider discovery.

Each peer announces its cached content by storing a JSON list of provider
descriptors at the content's object_id key. Lookups return all known providers
so the caller can apply locality-aware peer selection.

Read-modify-write is used for announcements so multiple peers can co-exist as
providers for the same object. This is safe for our simulation workloads where
concurrent announcements for the same object are rare; in a production system
you would use a CRDT or vector-clocked provider set.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

from kademlia.network import Server

from common.logging import get_logger

ANNOUNCE_OPERATION_TIMEOUT_SECONDS = 1.0


class DHTNode:
    def __init__(self, port: int, ksize: int = 5, alpha: int = 3, logger: Optional[logging.Logger] = None):
        """
        Args:
            port:   UDP port this node listens on.
            ksize:  Kademlia K — replication factor (number of closest nodes
                    that store each key). Lower values make data loss under
                    churn more visible, which is useful for our experiments.
            alpha:  Kademlia alpha — concurrency factor for lookups.
            logger: Optional logger; falls back to a module-level logger.
        """
        self.port = port
        self.server = Server(ksize=ksize, alpha=alpha)
        self.logger = logger or get_logger("dht.node")
        self._started = False

    async def start(self, bootstrap_nodes: Optional[List[tuple]] = None) -> None:
        """Start the DHT node and optionally bootstrap from known peers."""
        await self.server.listen(self.port)
        if bootstrap_nodes:
            await self.server.bootstrap(bootstrap_nodes)
        self._started = True
        self.logger.info(
            json.dumps({"event": "dht_started", "port": self.port, "bootstrap": bootstrap_nodes})
        )

    async def announce(self, object_id: str, peer_id: str, peer_url: str, location_id: str) -> bool:
        """
        Announce that this peer holds a cached copy of object_id.

        Performs a read-modify-write against the DHT so that the provider list
        grows as more peers cache the object.  Entries for this peer_id are
        refreshed (not duplicated) on repeated calls.

        Returns True on success, False if the DHT operation timed out or failed.
        """
        try:
            raw = await asyncio.wait_for(
                self.server.get(object_id),
                timeout=ANNOUNCE_OPERATION_TIMEOUT_SECONDS,
            )
            providers: List[Dict] = []
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        providers = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

            # Remove any stale entry for this peer then append the fresh one.
            providers = [p for p in providers if p.get("peer_id") != peer_id]
            providers.append({"peer_id": peer_id, "url": peer_url, "location_id": location_id})

            await asyncio.wait_for(
                self.server.set(object_id, json.dumps(providers)),
                timeout=ANNOUNCE_OPERATION_TIMEOUT_SECONDS,
            )
            return True
        except asyncio.TimeoutError:
            self.logger.warning(
                json.dumps({"event": "dht_announce_timeout", "object_id": object_id, "peer_id": peer_id})
            )
            return False
        except Exception as exc:
            self.logger.error(
                json.dumps({"event": "dht_announce_error", "object_id": object_id, "error": str(exc)})
            )
            return False

    async def announce_with_retry(
        self,
        object_id: str,
        peer_id: str,
        peer_url: str,
        location_id: str,
        attempts: int = 3,
        retry_delay_seconds: float = 0.2,
    ) -> bool:
        """
        Retry announcement a small number of times to reduce sensitivity to
        short-lived DHT convergence delays during experiments.
        """
        for attempt in range(1, attempts + 1):
            ok = await self.announce(object_id, peer_id, peer_url, location_id)
            if ok:
                return True
            if attempt < attempts:
                await asyncio.sleep(retry_delay_seconds)
        return False

    async def lookup(self, object_id: str) -> List[Dict]:
        """
        Return all known providers for object_id.

        Returns a list of dicts with keys: peer_id, url, location_id.
        Returns an empty list if no providers are found or parsing fails.
        Raises asyncio.TimeoutError if the internal DHT get exceeds its
        deadline (callers should wrap this in wait_for with their own budget).
        """
        raw = await self.server.get(object_id)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    async def remove_peer(self, peer_id: str, object_ids: List[str]) -> None:
        """
        Remove a peer from the provider lists for the given object_ids.

        Called on graceful shutdown so the DHT stays consistent. Because
        Kademlia has no delete primitive, this re-writes the provider list
        without the departing peer.
        """
        for object_id in object_ids:
            try:
                raw = await asyncio.wait_for(
                    self.server.get(object_id),
                    timeout=ANNOUNCE_OPERATION_TIMEOUT_SECONDS,
                )
                if not raw:
                    continue
                providers = json.loads(raw)
                if not isinstance(providers, list):
                    continue
                updated = [p for p in providers if p.get("peer_id") != peer_id]
                if len(updated) != len(providers):
                    await asyncio.wait_for(
                        self.server.set(object_id, json.dumps(updated)),
                        timeout=ANNOUNCE_OPERATION_TIMEOUT_SECONDS,
                    )
            except Exception:
                pass

    def stop(self) -> None:
        if self._started:
            self.server.stop()
            self._started = False
