"""Visibility filter enforcement at coordinator /lookup and peer /get-object."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def _import_coord_main(monkeypatch, *, auth_mode: str, auth_token: str = ""):
    """Re-import coordinator.main so it re-reads env vars."""
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    if auth_token:
        monkeypatch.setenv("AUTH_TOKEN", auth_token)
    for mod in list(sys.modules):
        if mod.startswith(("common", "coordinator")):
            del sys.modules[mod]
    return importlib.import_module("coordinator.main")


def test_coordinator_lookup_hides_restricted_object_from_wrong_group(monkeypatch):
    coord = _import_coord_main(monkeypatch, auth_mode="shared_token", auth_token="t")

    # Seed: register a peer, publish a restricted object for that peer.
    from common.schemas import ObjectMetadata, PublishRequest, RegisterRequest
    coord.store.register_peer(RegisterRequest(
        peer_id="peer-a1", host="h", port=1, location_id="Building-A",
    ))
    meta = ObjectMetadata(
        object_id="secret-exam",
        checksum="x" * 64,
        size_bytes=1,
        visibility="restricted",
        allowed_groups=["professors"],
    )
    coord.store.publish_object("peer-a1", meta)

    headers_auth = {"Authorization": "Bearer t"}
    with TestClient(coord.app) as c:
        # Wrong group: coordinator should respond with the same shape as
        # "object does not exist" (empty providers, metadata is None).
        r = c.get(
            "/lookup/secret-exam",
            params={"location_id": "Building-B"},
            headers={**headers_auth, "X-Peer-Id": "peer-b1", "X-Peer-Group": "students"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["providers"] == []
        assert body["metadata"] is None

        # Genuinely-nonexistent object: exact same shape — existence is unleakable.
        r2 = c.get(
            "/lookup/does-not-exist",
            params={"location_id": "Building-B"},
            headers={**headers_auth, "X-Peer-Id": "peer-b1", "X-Peer-Group": "students"},
        )
        assert r2.json()["providers"] == []
        assert r2.json()["metadata"] is None

        # Right group: providers returned + metadata present.
        r3 = c.get(
            "/lookup/secret-exam",
            params={"location_id": "Building-A"},
            headers={**headers_auth, "X-Peer-Id": "peer-a1", "X-Peer-Group": "professors"},
        )
        body3 = r3.json()
        assert body3["metadata"] is not None
        assert body3["metadata"]["visibility"] == "restricted"
        assert len(body3["providers"]) == 1


def test_peer_get_object_403_on_wrong_group(monkeypatch):
    """Peer-side defense-in-depth: /get-object returns 403 on group mismatch."""
    monkeypatch.setenv("AUTH_MODE", "shared_token")
    monkeypatch.setenv("AUTH_TOKEN", "t")
    monkeypatch.setenv("PEER_ID", "peer-a1")
    monkeypatch.setenv("PEER_GROUP", "professors")
    # Clear cached modules so peer.main re-reads settings.
    for mod in list(sys.modules):
        if mod.startswith(("common", "peer")):
            del sys.modules[mod]

    peer = importlib.import_module("peer.main")

    # Seed the peer's cache with a restricted object. Checksum must match content
    # for the cache's SHA-256 verification.
    import hashlib

    from common.schemas import ObjectMetadata
    content = b"bytes"
    meta = ObjectMetadata(
        object_id="secret-exam",
        checksum=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        visibility="restricted",
        allowed_groups=["professors"],
    )
    peer.cache.put(meta, content)

    # NOTE: we can't easily run TestClient(peer.app) with full lifespan because
    # it starts a DHT node + registers with the coordinator. Bypass lifespan by
    # calling the handler directly as a coroutine.
    import asyncio

    from common.auth import AuthContext

    async def call_get(group: str):
        from fastapi import HTTPException
        try:
            # Handler accepts object_id, requester_location_id, auth.
            return await peer.get_object(
                object_id="secret-exam",
                requester_location_id="Building-A",
                auth=AuthContext(mode="shared_token", peer_id="peer-b1", peer_group=group),
            )
        except HTTPException as e:
            return e

    # Wrong group → 403
    from fastapi import HTTPException
    result = asyncio.run(call_get("students"))
    assert isinstance(result, HTTPException)
    assert result.status_code == 403

    # Right group → dict with content_hex
    ok = asyncio.run(call_get("professors"))
    assert isinstance(ok, dict)
    assert "content_hex" in ok
