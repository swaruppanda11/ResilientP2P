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


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value


@dataclass(frozen=True)
class CommonSettings:
    heartbeat_interval_seconds: int
    peer_timeout_seconds: int
    cleanup_interval_seconds: int
    max_providers_per_lookup: int
    lookup_timeout_seconds: float
    intra_location_delay_ms: int
    inter_location_delay_ms: int
    origin_delay_ms: int


@dataclass(frozen=True)
class CoordinatorSettings(CommonSettings):
    provider_selection_policy: str
    service_name: str = "coordinator"


@dataclass(frozen=True)
class OriginSettings:
    origin_delay_ms: int
    service_name: str = "origin"


@dataclass(frozen=True)
class PeerSettings(CommonSettings):
    peer_id: str
    location_id: str
    coordinator_url: str
    origin_url: str
    host: str
    port: int
    cache_capacity_bytes: int
    # DHT fallback settings
    dht_port: int = 6000
    dht_bootstrap_host: str = "dht-bootstrap"
    dht_bootstrap_port: int = 6000
    dht_lookup_timeout_seconds: float = 0.5
    dht_republish_interval_seconds: int = 300
    service_name: str = "peer"


def get_common_settings() -> CommonSettings:
    return CommonSettings(
        heartbeat_interval_seconds=_get_int("HEARTBEAT_INTERVAL_SECONDS", 10),
        peer_timeout_seconds=_get_int("PEER_TIMEOUT_SECONDS", 30),
        cleanup_interval_seconds=_get_int("COORDINATOR_CLEANUP_INTERVAL_SECONDS", 10),
        max_providers_per_lookup=_get_int("MAX_PROVIDERS_PER_LOOKUP", 3),
        lookup_timeout_seconds=_get_float("LOOKUP_TIMEOUT_SECONDS", 2.0),
        intra_location_delay_ms=_get_int("INTRA_LOCATION_DELAY_MS", 5),
        inter_location_delay_ms=_get_int("INTER_LOCATION_DELAY_MS", 35),
        origin_delay_ms=_get_int("ORIGIN_DELAY_MS", 120),
    )


def get_coordinator_settings() -> CoordinatorSettings:
    common = get_common_settings()
    return CoordinatorSettings(
        heartbeat_interval_seconds=common.heartbeat_interval_seconds,
        peer_timeout_seconds=common.peer_timeout_seconds,
        cleanup_interval_seconds=common.cleanup_interval_seconds,
        max_providers_per_lookup=common.max_providers_per_lookup,
        lookup_timeout_seconds=common.lookup_timeout_seconds,
        intra_location_delay_ms=common.intra_location_delay_ms,
        inter_location_delay_ms=common.inter_location_delay_ms,
        origin_delay_ms=common.origin_delay_ms,
        provider_selection_policy=_get_str("PROVIDER_SELECTION_POLICY", "locality_then_load"),
    )


def get_origin_settings() -> OriginSettings:
    common = get_common_settings()
    return OriginSettings(origin_delay_ms=common.origin_delay_ms)


def get_peer_settings() -> PeerSettings:
    common = get_common_settings()
    peer_id = os.getenv("PEER_ID", f"peer-{socket.gethostname()}")
    return PeerSettings(
        heartbeat_interval_seconds=common.heartbeat_interval_seconds,
        peer_timeout_seconds=common.peer_timeout_seconds,
        cleanup_interval_seconds=common.cleanup_interval_seconds,
        max_providers_per_lookup=common.max_providers_per_lookup,
        lookup_timeout_seconds=common.lookup_timeout_seconds,
        intra_location_delay_ms=common.intra_location_delay_ms,
        inter_location_delay_ms=common.inter_location_delay_ms,
        origin_delay_ms=common.origin_delay_ms,
        peer_id=peer_id,
        location_id=os.getenv("LOCATION_ID", "Building-A"),
        coordinator_url=os.getenv("COORDINATOR_URL", "http://coordinator:8000"),
        origin_url=os.getenv("ORIGIN_URL", "http://origin:8001"),
        host=os.getenv("PEER_HOST", peer_id),
        port=_get_int("PEER_PORT", 7000),
        cache_capacity_bytes=_get_int("CACHE_CAPACITY_BYTES", 10 * 1024 * 1024),
        dht_port=_get_int("DHT_PORT", 6000),
        dht_bootstrap_host=_get_str("DHT_BOOTSTRAP_HOST", "dht-bootstrap"),
        dht_bootstrap_port=_get_int("DHT_BOOTSTRAP_PORT", 6000),
        dht_lookup_timeout_seconds=_get_float("DHT_LOOKUP_TIMEOUT_SECONDS", 0.5),
        dht_republish_interval_seconds=_get_int("DHT_REPUBLISH_INTERVAL_SECONDS", 300),
    )
