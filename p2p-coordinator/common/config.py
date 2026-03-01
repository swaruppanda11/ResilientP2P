import os
import socket
from dataclasses import dataclass


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class CommonSettings:
    heartbeat_interval_seconds: int
    peer_timeout_seconds: int
    cleanup_interval_seconds: int
    max_providers_per_lookup: int
    lookup_timeout_seconds: float


@dataclass(frozen=True)
class CoordinatorSettings(CommonSettings):
    service_name: str = "coordinator"


@dataclass(frozen=True)
class PeerSettings(CommonSettings):
    peer_id: str
    location_id: str
    coordinator_url: str
    origin_url: str
    host: str
    port: int
    service_name: str = "peer"


def get_common_settings() -> CommonSettings:
    return CommonSettings(
        heartbeat_interval_seconds=_get_int("HEARTBEAT_INTERVAL_SECONDS", 10),
        peer_timeout_seconds=_get_int("PEER_TIMEOUT_SECONDS", 30),
        cleanup_interval_seconds=_get_int("COORDINATOR_CLEANUP_INTERVAL_SECONDS", 10),
        max_providers_per_lookup=_get_int("MAX_PROVIDERS_PER_LOOKUP", 3),
        lookup_timeout_seconds=_get_float("LOOKUP_TIMEOUT_SECONDS", 2.0),
    )


def get_coordinator_settings() -> CoordinatorSettings:
    common = get_common_settings()
    return CoordinatorSettings(
        heartbeat_interval_seconds=common.heartbeat_interval_seconds,
        peer_timeout_seconds=common.peer_timeout_seconds,
        cleanup_interval_seconds=common.cleanup_interval_seconds,
        max_providers_per_lookup=common.max_providers_per_lookup,
        lookup_timeout_seconds=common.lookup_timeout_seconds,
    )


def get_peer_settings() -> PeerSettings:
    common = get_common_settings()
    peer_id = os.getenv("PEER_ID", f"peer-{socket.gethostname()}")
    return PeerSettings(
        heartbeat_interval_seconds=common.heartbeat_interval_seconds,
        peer_timeout_seconds=common.peer_timeout_seconds,
        cleanup_interval_seconds=common.cleanup_interval_seconds,
        max_providers_per_lookup=common.max_providers_per_lookup,
        lookup_timeout_seconds=common.lookup_timeout_seconds,
        peer_id=peer_id,
        location_id=os.getenv("LOCATION_ID", "Building-A"),
        coordinator_url=os.getenv("COORDINATOR_URL", "http://coordinator:8000"),
        origin_url=os.getenv("ORIGIN_URL", "http://origin:8001"),
        host=os.getenv("PEER_HOST", peer_id),
        port=_get_int("PEER_PORT", 7000),
    )
