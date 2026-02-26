from pydantic import BaseModel, Field
from datetime import datetime
import json

class MetricEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    source_peer: str
    event_type: str  # "CACHE_HIT", "CACHE_MISS", "PEER_FETCH", "ORIGIN_FETCH"
    object_id: str
    latency_ms: float
    location_id: str

def log_metric(event: MetricEvent):
    # For now, just print as JSON; in production, write to a shared volume or DB
    print(f"METRIC: {event.json()}")
