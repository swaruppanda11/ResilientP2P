from pydantic import BaseModel, Field
from typing import List, Optional
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
