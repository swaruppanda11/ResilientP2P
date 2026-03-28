from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class MetricEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    source_peer: str
    event_type: str
    object_id: str
    latency_ms: float
    location_id: str
    bytes_transferred: int = 0
    provider_peer: Optional[str] = None
    candidate_count: Optional[int] = None
    evicted_bytes: int = 0
    evicted_count: int = 0
    cache_capacity_bytes: Optional[int] = None
    cache_size_bytes: Optional[int] = None
    cache_object_count: Optional[int] = None


def log_metric(event: MetricEvent):
    if hasattr(event, "model_dump_json"):
        payload = event.model_dump_json()
    else:
        payload = event.json()
    print(f"METRIC: {payload}")
