"""
Peer auth primitives (Workstream 2).

Three modes, set by AUTH_MODE:
  - none         : dependency is a no-op, outbound auth is a no-op.
  - permissive   : validate token if present; still allow on missing/invalid.
                   Used during rollout to surface misconfigured pods without
                   breaking traffic. Never a terminal state.
  - shared_token : strict; 401 on missing/invalid Authorization header.

Identity (X-Peer-Id, X-Peer-Group) is client-asserted. The shared token gates
the campus trust boundary; cryptographic identity binding waits for cert mode.
Always log these headers prefixed with `claimed_peer_id=` / `claimed_group=`
and use `sanitize_header_value` before logging to defeat log injection.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException, Request

from common.config import AuthSettings, get_auth_settings
from common.logging import get_logger, log_event


MAX_HEADER_LEN = 128

VALID_MODES = {"none", "permissive", "shared_token"}

_logger = get_logger("auth")


@dataclass(frozen=True)
class AuthContext:
    """Per-request auth state stashed on `request.state.auth`."""
    mode: str
    peer_id: Optional[str]
    peer_group: Optional[str]


def sanitize_header_value(raw: Optional[str]) -> Optional[str]:
    """Strip non-printable characters and length-cap for safe logging."""
    if raw is None:
        return None
    cleaned = "".join(c for c in raw if c.isprintable() and c not in ("\n", "\r"))
    if len(cleaned) > MAX_HEADER_LEN:
        cleaned = cleaned[:MAX_HEADER_LEN] + "..."
    return cleaned


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency. Returns an AuthContext; raises 401 in strict mode.

    Stashes context on `request.state.auth` for handlers that need the caller's
    claimed identity (e.g. visibility enforcement).
    """
    settings: AuthSettings = get_auth_settings()
    mode = settings.mode if settings.mode in VALID_MODES else "none"

    claimed_peer_id = sanitize_header_value(request.headers.get("x-peer-id"))
    claimed_group = sanitize_header_value(request.headers.get("x-peer-group"))
    bearer = _extract_bearer(request.headers.get("authorization"))

    if mode == "none":
        ctx = AuthContext(mode=mode, peer_id=claimed_peer_id, peer_group=claimed_group)
        request.state.auth = ctx
        return ctx

    token_ok = bool(bearer) and bool(settings.token) and hmac.compare_digest(
        bearer.encode(), settings.token.encode()
    )

    if mode == "permissive":
        if not bearer:
            log_event(
                _logger, logging.WARNING, "auth.missing",
                claimed_peer_id=claimed_peer_id, mode=mode,
            )
        elif not token_ok:
            log_event(
                _logger, logging.WARNING, "auth.invalid",
                claimed_peer_id=claimed_peer_id, mode=mode,
            )
        ctx = AuthContext(mode=mode, peer_id=claimed_peer_id, peer_group=claimed_group)
        request.state.auth = ctx
        return ctx

    # shared_token: strict
    if not token_ok:
        log_event(
            _logger, logging.WARNING,
            "auth.rejected",
            reason="missing" if not bearer else "invalid",
            claimed_peer_id=claimed_peer_id, mode=mode,
        )
        raise HTTPException(status_code=401, detail="unauthorized")
    ctx = AuthContext(mode=mode, peer_id=claimed_peer_id, peer_group=claimed_group)
    request.state.auth = ctx
    return ctx


class _OutboundAuth(httpx.Auth):
    """Attaches Authorization + identity headers to every outgoing request.

    Using an httpx.Auth subclass rather than AsyncClient(headers=...) so
    per-call header merges can't silently drop the token.
    """

    def __init__(self, token: str, peer_id: str, peer_group: str):
        self._token = token
        self._peer_id = peer_id
        self._peer_group = peer_group

    def auth_flow(self, request):
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        if self._peer_id:
            request.headers["X-Peer-Id"] = self._peer_id
        if self._peer_group:
            request.headers["X-Peer-Group"] = self._peer_group
        yield request


class _NoopAuth(httpx.Auth):
    def auth_flow(self, request):
        yield request


def outbound_auth(
    peer_id: str = "",
    peer_group: Optional[str] = None,
) -> httpx.Auth:
    """Return an httpx.Auth to pass as AsyncClient(auth=...).

    In AUTH_MODE=none returns a no-op so outbound traffic is unchanged.
    Otherwise attaches the shared token + claimed peer_id/peer_group.
    """
    settings = get_auth_settings()
    if settings.mode == "none" or not settings.token:
        return _NoopAuth()
    group = peer_group if peer_group is not None else settings.peer_group
    return _OutboundAuth(token=settings.token, peer_id=peer_id, peer_group=group)
