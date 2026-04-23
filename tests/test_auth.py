"""Workstream 2 auth tests: backwards-compat, strict mode, /health public, outbound audit."""

import os

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    """Fresh FastAPI app wired with the real require_auth dependency.

    Constructed inside each test so the module picks up test-local env vars.
    """
    from common.auth import AuthContext, require_auth

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/gated")
    def gated(ctx: AuthContext = Depends(require_auth)):
        return {"peer": ctx.peer_id, "group": ctx.peer_group, "mode": ctx.mode}

    return app


# --- Test 1: Backwards-compat (AUTH_MODE=none) ---

def test_none_mode_allows_unauthenticated(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    with TestClient(_build_app()) as c:
        r = c.get("/gated")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "none"
        assert body["peer"] is None


# --- Test 2: Strict mode (AUTH_MODE=shared_token) ---

def test_strict_mode_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "shared_token")
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    with TestClient(_build_app()) as c:
        assert c.get("/gated").status_code == 401


def test_strict_mode_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "shared_token")
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    with TestClient(_build_app()) as c:
        r = c.get("/gated", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


def test_strict_mode_accepts_valid_token(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "shared_token")
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    with TestClient(_build_app()) as c:
        r = c.get(
            "/gated",
            headers={
                "Authorization": "Bearer s3cret",
                "X-Peer-Id": "peer-a1",
                "X-Peer-Group": "professors",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["peer"] == "peer-a1"
        assert body["group"] == "professors"


# --- Test 3: /health never gated across modes ---

@pytest.mark.parametrize("mode", ["none", "permissive", "shared_token"])
def test_health_always_public(monkeypatch, mode):
    monkeypatch.setenv("AUTH_MODE", mode)
    monkeypatch.setenv("AUTH_TOKEN", "s3cret" if mode != "none" else "")
    with TestClient(_build_app()) as c:
        r = c.get("/health")
        assert r.status_code == 200, f"/health should be public in {mode} mode"


# --- Test 4: Outbound header audit ---

@pytest.mark.asyncio
async def test_outbound_auth_attaches_all_three_headers(monkeypatch):
    """Every PeerClient outbound call must carry Authorization + X-Peer-Id + X-Peer-Group."""
    monkeypatch.setenv("AUTH_MODE", "shared_token")
    monkeypatch.setenv("AUTH_TOKEN", "abc123")
    monkeypatch.setenv("PEER_GROUP", "professors")
    monkeypatch.setenv("PEER_ID", "peer-a1")

    captured: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        # Minimal shaped responses to keep the client from choking.
        if request.url.path == "/register":
            return httpx.Response(200, json={"status": "registered", "peer_id": "peer-a1"})
        if request.url.path == "/heartbeat":
            return httpx.Response(200, json={"status": "ok", "peer_id": "peer-a1"})
        if request.url.path == "/publish":
            return httpx.Response(200, json={
                "status": "published", "peer_id": "peer-a1", "object_id": "obj",
            })
        if request.url.path == "/report-transfer":
            return httpx.Response(200, json={
                "status": "ok", "peer_id": "peer-a1",
                "total_upload_requests": 1, "total_upload_bytes": 0,
            })
        return httpx.Response(200, json={})

    from common.auth import outbound_auth

    # Build an AsyncClient with the same auth= our PeerClient constructs with,
    # but swap the transport for our mock so requests stay in-process.
    auth = outbound_auth(peer_id="peer-a1")
    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(
        base_url="http://coordinator", auth=auth, transport=transport
    ) as client:
        await client.post("/register", json={
            "peer_id": "peer-a1", "host": "h", "port": 1, "location_id": "L",
        })
        await client.post("/heartbeat", json={"peer_id": "peer-a1"})
        await client.post("/publish", json={
            "peer_id": "peer-a1",
            "metadata": {
                "object_id": "obj", "checksum": "x" * 64, "size_bytes": 1,
            },
        })
        await client.post("/report-transfer", json={
            "peer_id": "peer-a1", "object_id": "obj", "bytes_served": 0,
        })

    assert len(captured) == 4
    for req in captured:
        assert req.headers.get("authorization") == "Bearer abc123", req.url
        assert req.headers.get("x-peer-id") == "peer-a1", req.url
        assert req.headers.get("x-peer-group") == "professors", req.url


# --- Bonus: sanitization strips newlines before logging ---

def test_sanitize_strips_newlines():
    from common.auth import sanitize_header_value
    assert "\n" not in (sanitize_header_value("a\nb") or "")
    assert "\r" not in (sanitize_header_value("a\rb") or "")
    long = "x" * 500
    out = sanitize_header_value(long)
    assert len(out) <= 150  # MAX_HEADER_LEN (128) + ellipsis


@pytest.fixture
def anyio_backend():  # pragma: no cover
    return "asyncio"
