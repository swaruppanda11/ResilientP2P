"""Workstream 3 reputation tests — load-bearing only.

Coverage (mirrors WS2 discipline):
  1. State machine transitions (healthy→suspect→quarantined→cooldown→healthy).
  2. Rate limit + self-report guard.
  3. Provider filtering (quarantined excluded, suspect ranked last).
  4. Publish-conflict attribution (the publishing peer gets the incident).
  5. Peer-side report on checksum mismatch (PeerClient fires /report-bad-peer).
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from datetime import datetime
from typing import Optional

import httpx
import pytest


# --- Test 1: Reputation state machine ---------------------------------------


def _build_tracker(threshold_suspect=1.0, threshold_quarantine=3.0, cooldown=60):
    from common.config import ReputationSettings
    from coordinator.reputation import ReputationTracker

    t = [0.0]
    settings = ReputationSettings(
        enabled=True,
        suspect_threshold=threshold_suspect,
        quarantine_threshold=threshold_quarantine,
        cooldown_seconds=cooldown,
        report_dedupe_window_seconds=10,
        origin_exempt_peer_ids=("origin",),
    )
    tracker = ReputationTracker(settings, clock=lambda: t[0])
    return tracker, t


def test_state_machine_full_lifecycle():
    from coordinator.reputation import HEALTHY, QUARANTINED, SUSPECT

    tracker, t = _build_tracker()

    # 1 checksum_mismatch (weight 1.0) → suspect
    rep = tracker.record_incident("peer-x", "checksum_mismatch",
                                  reporter_peer_id="peer-y", object_id="o1")
    assert rep.state == SUSPECT, rep.state

    # +metadata_conflict (2.0) → score 3.0 → quarantined
    rep = tracker.record_incident("peer-x", "metadata_conflict")
    assert rep.state == QUARANTINED
    assert rep.quarantined_at == 0.0

    # Mid-cooldown incident: clock should reset.
    t[0] = 30.0
    rep = tracker.record_incident("peer-x", "unavailable",
                                  reporter_peer_id="peer-z", object_id="o2")
    assert rep.state == QUARANTINED
    assert rep.quarantined_at == 30.0, "cooldown clock must reset on new incident"

    # Cooldown not yet elapsed (30 + 60 = 90, not yet at 89)
    t[0] = 89.0
    assert tracker.tick_cooldowns() == []
    assert tracker.is_quarantined("peer-x")

    # Cooldown elapsed
    t[0] = 91.0
    recovered = tracker.tick_cooldowns()
    assert recovered == ["peer-x"]
    rep_after = tracker.get("peer-x")
    # Counters HALVED, not zeroed (re-offender escalates faster).
    assert rep_after.score < 4.5  # was 4.5, halved to 2.25
    assert rep_after.state == SUSPECT  # still over suspect threshold (1.0)
    # After full halving the integer counters must round down, not stay full.
    assert rep_after.checksum_mismatches < 1 or rep_after.metadata_conflicts < 1


# --- Test 2: Rate limit + self-report guard ---------------------------------


def test_dedupe_within_window_drops_repeat():
    tracker, t = _build_tracker()

    r1 = tracker.record_incident("peer-x", "checksum_mismatch",
                                 reporter_peer_id="peer-y", object_id="o1")
    assert r1 is not None

    # Same triple within 10s — dropped.
    t[0] = 5.0
    r2 = tracker.record_incident("peer-x", "checksum_mismatch",
                                 reporter_peer_id="peer-y", object_id="o1")
    assert r2 is None, "same (reporter, accused, object_id) within window must be dropped"


def test_different_object_passes_dedupe():
    tracker, t = _build_tracker()
    tracker.record_incident("peer-x", "checksum_mismatch",
                            reporter_peer_id="peer-y", object_id="o1")
    t[0] = 5.0
    r = tracker.record_incident("peer-x", "checksum_mismatch",
                                reporter_peer_id="peer-y", object_id="o2")
    assert r is not None


def test_self_report_dropped():
    tracker, _ = _build_tracker()
    r = tracker.record_incident("peer-x", "checksum_mismatch",
                                reporter_peer_id="peer-x", object_id="o1")
    assert r is None


def test_origin_exempt_from_reputation():
    tracker, _ = _build_tracker()
    r = tracker.record_incident("origin", "metadata_conflict")
    assert r is None
    # Origin must always read as healthy regardless of incidents.
    assert tracker.is_quarantined("origin") is False


# --- Test 3: Provider filtering ---------------------------------------------


def test_get_providers_filters_quarantined_and_ranks_suspect_last(monkeypatch):
    monkeypatch.setenv("REPUTATION_ENABLED", "true")
    # Reset cached modules so fresh settings take effect.
    for m in list(sys.modules):
        if m.startswith(("common", "coordinator")):
            del sys.modules[m]

    coord_main = importlib.import_module("coordinator.main")
    store = coord_main.store
    tracker = coord_main.reputation_tracker
    assert store.reputation is tracker, "store must be wired with the tracker"

    from common.schemas import ObjectMetadata, RegisterRequest

    for pid, loc in (("peer-a1", "Building-A"), ("peer-a2", "Building-A"), ("peer-b1", "Building-B")):
        store.register_peer(RegisterRequest(peer_id=pid, host=pid, port=7000, location_id=loc))
    meta = ObjectMetadata(object_id="x", checksum="x" * 64, size_bytes=1)
    for pid in ("peer-a1", "peer-a2", "peer-b1"):
        store.publish_object(pid, meta)

    # Quarantine peer-a1, suspect peer-a2; peer-b1 stays healthy.
    for _ in range(3):  # 3 metadata_conflicts = 6.0 score → quarantined
        tracker.record_incident("peer-a1", "metadata_conflict")
    tracker.record_incident("peer-a2", "checksum_mismatch",
                            reporter_peer_id="peer-b1", object_id="x")

    providers = store.get_providers("x", "Building-A")
    # peer-a1 must be filtered out entirely.
    assert all("peer-a1" not in p for p in providers), providers
    # peer-a2 (suspect) ranks AFTER peer-b1 (healthy) despite locality preference.
    a2_idx = next(i for i, p in enumerate(providers) if "peer-a2" in p)
    b1_idx = next(i for i, p in enumerate(providers) if "peer-b1" in p)
    assert b1_idx < a2_idx, f"healthy should outrank suspect: {providers}"


# --- Test 4: Publish-conflict attribution -----------------------------------


def test_publish_conflict_attributes_to_publisher(monkeypatch):
    monkeypatch.setenv("REPUTATION_ENABLED", "true")
    for m in list(sys.modules):
        if m.startswith(("common", "coordinator")):
            del sys.modules[m]
    coord_main = importlib.import_module("coordinator.main")
    store = coord_main.store
    tracker = coord_main.reputation_tracker

    from common.schemas import ObjectMetadata, RegisterRequest
    from coordinator.store import InvalidPublishError

    for pid in ("peer-honest", "peer-bad"):
        store.register_peer(RegisterRequest(peer_id=pid, host=pid, port=7000, location_id="Building-A"))

    canonical = ObjectMetadata(object_id="obj", checksum="a" * 64, size_bytes=1)
    bad = ObjectMetadata(object_id="obj", checksum="b" * 64, size_bytes=1)

    # Honest peer publishes first — should NOT be attributed.
    store.publish_object("peer-honest", canonical)

    # Bad peer publishes a conflicting version — attribution lands on the publisher.
    with pytest.raises(InvalidPublishError):
        store.publish_object("peer-bad", bad)

    assert tracker.get("peer-honest") is None, "honest peer must not be flagged"
    bad_rep = tracker.get("peer-bad")
    assert bad_rep is not None
    # Weight 2.0 for metadata_conflict crosses the 1.0 suspect threshold
    # and reaches the 3.0 quarantine threshold only with multiple conflicts.
    # One conflict on a fresh peer puts them at suspect.
    assert bad_rep.metadata_conflicts == 1
    assert bad_rep.score == 2.0


def test_quarantined_peer_cannot_publish(monkeypatch):
    monkeypatch.setenv("REPUTATION_ENABLED", "true")
    for m in list(sys.modules):
        if m.startswith(("common", "coordinator")):
            del sys.modules[m]
    coord_main = importlib.import_module("coordinator.main")
    store = coord_main.store
    tracker = coord_main.reputation_tracker

    from common.schemas import ObjectMetadata, RegisterRequest
    from coordinator.store import QuarantinedPublisherError

    store.register_peer(RegisterRequest(peer_id="peer-bad", host="h", port=1, location_id="L"))
    # Force quarantine.
    for _ in range(3):
        tracker.record_incident("peer-bad", "metadata_conflict")
    assert tracker.is_quarantined("peer-bad")

    with pytest.raises(QuarantinedPublisherError):
        store.publish_object("peer-bad", ObjectMetadata(
            object_id="x", checksum="c" * 64, size_bytes=1,
        ))


# --- Test 5: Peer-side report on checksum mismatch --------------------------


@pytest.mark.asyncio
async def test_peer_client_reports_on_checksum_mismatch(monkeypatch):
    """The coord-stack PeerClient should fire /report-bad-peer to the
    coordinator when a peer fetch returns bytes that don't match metadata."""
    monkeypatch.setenv("REPUTATION_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("PEER_ID", "peer-honest")
    for m in list(sys.modules):
        if m.startswith(("common", "peer", "dht")):
            del sys.modules[m]

    from common.schemas import ObjectMetadata
    from peer.cache import Cache
    from peer.client import PeerClient

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/lookup/badobj":
            return httpx.Response(200, json={
                "object_id": "badobj",
                "providers": ["http://peer-evil:7000"],
                "metadata": {
                    "object_id": "badobj",
                    "checksum": hashlib.sha256(b"correct").hexdigest(),
                    "size_bytes": 7,
                },
            })
        if request.url.path == "/get-object/badobj":
            # Wrong bytes — checksum will mismatch.
            return httpx.Response(200, json={
                "content_hex": b"corrupt".hex(),
                "metadata": None,
            })
        if request.url.path == "/object/badobj":
            return httpx.Response(200, json={
                "object_id": "badobj",
                "content_hex": b"correct".hex(),
                "checksum": hashlib.sha256(b"correct").hexdigest(),
                "size": 7,
                "version": "1",
                "cacheability": "immutable",
            })
        if request.url.path == "/report-bad-peer":
            return httpx.Response(200, json={
                "status": "recorded",
                "accused_peer_id": "peer-evil",
                "snapshot": {
                    "peer_id": "peer-evil", "state": "suspect", "score": 1.0,
                },
            })
        return httpx.Response(200, json={})

    # Build a minimal client with the real outbound auth pipeline + mock transport.
    cache = Cache(capacity_bytes=10 * 1024 * 1024)

    class _StubDHT:
        async def lookup(self, *a, **kw):
            return []
        async def announce_with_retry(self, *a, **kw):
            return True

    client = PeerClient(
        peer_id="peer-honest",
        location_id="Building-A",
        coordinator_url="http://coordinator",
        origin_url="http://origin",
        cache=cache,
        dht_node=_StubDHT(),
    )
    client.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await client.fetch_object("badobj")
    # Checksum mismatch on peer fetch → falls through to origin and succeeds.
    assert result is not None
    assert result.source == "origin"

    # Drain the fire-and-forget report task.
    import asyncio
    await asyncio.sleep(0.1)

    report_paths = [r for r in captured if r.url.path == "/report-bad-peer"]
    assert report_paths, f"expected /report-bad-peer call, got {[r.url.path for r in captured]}"
    import json as _json
    body = _json.loads(report_paths[0].read().decode())
    assert body["reason"] == "checksum_mismatch"
    assert body["accused_peer_id"] == "peer-evil"
    assert body["object_id"] == "badobj"
