from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime

class ObjectMetadata(BaseModel):
    object_id: str
    checksum: str  # SHA-256 hash
    size_bytes: int

class PeerInfo(BaseModel):
    peer_id: str
    url: str
    location_id: str  # Simulated Subnet/Building ID
    last_seen: datetime

class RegisterRequest(BaseModel):
    peer_id: str
    host: str
    port: int
    location_id: str

class PublishRequest(BaseModel):
    peer_id: str
    metadata: ObjectMetadata

class LookupResponse(BaseModel):
    object_id: str
    providers: List[str]  # List of Peer URLs, sorted by locality
    metadata: Optional[ObjectMetadata] = None

class HeartbeatRequest(BaseModel):
    peer_id: str


class RegisterResponse(BaseModel):
    status: str
    peer_id: str


class PublishResponse(BaseModel):
    status: str
    peer_id: str
    object_id: str


class HeartbeatResponse(BaseModel):
    status: str
    peer_id: str


class HealthResponse(BaseModel):
    status: str
    service: str


class CoordinatorStatsResponse(BaseModel):
    status: str
    service: str
    peer_count: int
    object_count: int
    provider_entries: int
    max_providers_per_lookup: int
    peer_timeout_seconds: int


class PeerStatsResponse(BaseModel):
    status: str
    service: str
    peer_id: str
    location_id: str
    cache_capacity_bytes: int
    cache_size_bytes: int
    cache_object_count: int
    cache_hit_count: int
    cache_miss_count: int
    cache_eviction_count: int
    cache_rejected_write_count: int


class ErrorResponse(BaseModel):
    detail: str
    error_code: str


class LogEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    service: str
    level: str
    event: str
    details: Dict[str, Any] = Field(default_factory=dict)
