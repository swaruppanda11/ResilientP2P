from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime


class ObjectMetadata(BaseModel):
    object_id: str
    checksum: str  # SHA-256 hash
    size_bytes: int
    version: str = "1"
    cacheability: str = "immutable"  # immutable | ttl | dynamic
    max_age_seconds: Optional[int] = None
    expires_at: Optional[datetime] = None
    etag: Optional[str] = None
    # Access control (Workstream 2). Defaults are backwards-compatible: every
    # existing publish round-trips as public with no group restrictions.
    visibility: str = "public"  # public | restricted
    allowed_groups: List[str] = Field(default_factory=list)
    owner: Optional[str] = None


class InvalidateResponse(BaseModel):
    status: str
    object_id: str
    removed_provider_entries: int = 0
    notified_peers: int = 0


class PeerInfo(BaseModel):
    peer_id: str
    url: str
    location_id: str
    last_seen: datetime


class PeerLoadStats(BaseModel):
    peer_id: str
    total_upload_requests: int = 0
    total_upload_bytes: int = 0
    last_transfer_at: Optional[datetime] = None


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
    providers: List[str]  # List of peer URLs, sorted by locality
    metadata: Optional[ObjectMetadata] = None


class HeartbeatRequest(BaseModel):
    peer_id: str


class TransferReportRequest(BaseModel):
    peer_id: str
    object_id: str
    bytes_served: int


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


class TransferReportResponse(BaseModel):
    status: str
    peer_id: str
    total_upload_requests: int
    total_upload_bytes: int


class HealthResponse(BaseModel):
    status: str
    service: str


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


class PeerFetchResponse(BaseModel):
    status: str
    object_id: str
    source: str
    size: int
    latency_ms: float
    candidate_count: int = 0
    provider: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
    error_code: str


class LogEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    service: str
    level: str
    event: str
    details: Dict[str, Any] = Field(default_factory=dict)
