#!/usr/bin/env python3
"""
Deterministic validation for Workstream 1: dynamic object invalidation.

This script avoids Docker/GKE and directly exercises the cache, coordinator
store, and DHT provider-filtering logic that backs the runtime scenarios.
Run from the repository root:

    python -B scripts/validate-dynamic-invalidation.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _purge_project_modules() -> None:
    for name in list(sys.modules):
        if name in {"common", "peer", "coordinator", "dht"} or name.startswith(
            ("common.", "peer.", "coordinator.", "dht.")
        ):
            del sys.modules[name]


def _use_stack(stack_dir: str) -> None:
    _purge_project_modules()
    stack_path = str(ROOT / stack_dir)
    sys.path = [p for p in sys.path if not p.endswith("p2p-coordinator") and not p.endswith("p2p-dht")]
    sys.path.insert(0, stack_path)


class FakeDHTServer:
    def __init__(self, providers):
        self.providers = providers

    async def get(self, _object_id):
        return json.dumps(self.providers)

    async def set(self, _object_id, _value):
        return None

    def stop(self):
        return None


def _install_fake_kademlia() -> None:
    if "kademlia.network" in sys.modules:
        return
    kademlia_module = types.ModuleType("kademlia")
    network_module = types.ModuleType("kademlia.network")
    network_module.Server = lambda *args, **kwargs: FakeDHTServer([])
    sys.modules["kademlia"] = kademlia_module
    sys.modules["kademlia.network"] = network_module


def _metadata(object_id: str, data: bytes = b"data", **kwargs):
    from common.schemas import ObjectMetadata

    return ObjectMetadata(
        object_id=object_id,
        checksum=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        **kwargs,
    )


def validate_coordinator_stack() -> None:
    _use_stack("p2p-coordinator")
    _install_fake_kademlia()

    from common.schemas import RegisterRequest
    from coordinator.store import Store
    from dht.node import DHTNode
    from peer.cache import Cache

    expired = _metadata(
        "ttl-expired",
        data=b"data",
        cacheability="ttl",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    cache = Cache(capacity_bytes=1024)
    cache.storage["ttl-expired"] = b"data"
    cache.metadata["ttl-expired"] = expired
    cache.current_size_bytes = 4
    assert cache.get("ttl-expired") is None
    assert cache.current_size_bytes == 0

    cache.put(_metadata("prefix/a", data=b"\x31"), b"\x31")
    cache.put(_metadata("prefix/b", data=b"\x31"), b"\x31")
    cache.put(_metadata("other/c", data=b"\x31"), b"\x31")
    removed = cache.invalidate_prefix("prefix/")
    assert removed == ["prefix/a", "prefix/b"]
    assert cache.get("prefix/a") is None
    assert cache.get("other/c") == b"\x31"

    store = Store(max_providers_per_lookup=2)
    store.register_peer(RegisterRequest(peer_id="p1", host="peer1", port=8080, location_id="A"))
    store.register_peer(RegisterRequest(peer_id="p2", host="peer2", port=8080, location_id="A"))
    store.publish_object("p1", _metadata("mutable", version="1"))
    assert store.get_providers("mutable", "A", version="1") == ["http://peer1:8080"]
    assert store.get_providers("mutable", "A", version="2") == []
    store.publish_object("p2", _metadata("mutable", data=b"v2", version="2"))
    assert store.get_providers("mutable", "A", version="2") == ["http://peer2:8080"]
    assert "http://peer1:8080" not in store.get_providers("mutable", "A", version="2")

    providers, removed_count = store.invalidate_object("mutable")
    assert providers == ["http://peer1:8080", "http://peer2:8080"]
    assert removed_count == 2
    assert store.get_object_metadata("mutable") is None

    store.publish_object("p1", _metadata("course/unit-1"))
    store.publish_object("p2", _metadata("course/unit-2"))
    provider_urls, removed_count, object_ids = store.invalidate_prefix("course/")
    assert provider_urls == ["http://peer1:8080", "http://peer2:8080"]
    assert removed_count == 2
    assert object_ids == ["course/unit-1", "course/unit-2"]

    node = DHTNode(port=9999)
    node.server = FakeDHTServer(
        [
            {"peer_id": "p1", "url": "http://p1", "location_id": "A", "version": "1", "cacheability": "immutable"},
            {"peer_id": "p2", "url": "http://p2", "location_id": "A", "version": "2", "cacheability": "immutable"},
            {
                "peer_id": "p3",
                "url": "http://p3",
                "location_id": "A",
                "version": "2",
                "cacheability": "ttl",
                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            },
        ]
    )
    providers = asyncio.run(node.lookup("mutable", version="2"))
    assert [p["peer_id"] for p in providers] == ["p2"]


def validate_dht_stack() -> None:
    _use_stack("p2p-dht")
    _install_fake_kademlia()

    from dht.node import DHTNode
    from peer.cache import Cache

    cache = Cache(capacity_bytes=1024)
    cache.put(_metadata("prefix/a", data=b"\x31"), b"\x31")
    cache.put(_metadata("prefix/b", data=b"\x31"), b"\x31")
    assert cache.invalidate_prefix("prefix/") == ["prefix/a", "prefix/b"]
    assert cache.get("prefix/a") is None

    node = DHTNode(port=9998)
    node.server = FakeDHTServer(
        [
            {"peer_id": "p1", "url": "http://p1", "location_id": "A", "version": "1", "cacheability": "immutable"},
            {"peer_id": "p2", "url": "http://p2", "location_id": "A", "version": "2", "cacheability": "immutable"},
        ]
    )
    providers = asyncio.run(node.lookup("mutable", version="2"))
    assert [p["peer_id"] for p in providers] == ["p2"]


def main() -> None:
    validate_coordinator_stack()
    validate_dht_stack()
    print("Workstream 1 validation passed")


if __name__ == "__main__":
    main()
