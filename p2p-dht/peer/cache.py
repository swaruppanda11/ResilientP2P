import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

from common.schemas import ObjectMetadata


@dataclass(frozen=True)
class CacheWriteResult:
    stored: bool
    evicted_object_ids: List[str]
    evicted_bytes: int
    object_size_bytes: int


class Cache:
    def __init__(self, capacity_bytes: int):
        if capacity_bytes <= 0:
            raise ValueError("Cache capacity must be positive")

        self.capacity_bytes = capacity_bytes
        self.current_size_bytes = 0
        self.storage: "OrderedDict[str, bytes]" = OrderedDict()
        self.metadata: Dict[str, ObjectMetadata] = {}
        self.hit_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        self.rejected_write_count = 0

    def put(self, metadata: ObjectMetadata, data: bytes) -> CacheWriteResult:
        checksum = hashlib.sha256(data).hexdigest()
        if checksum != metadata.checksum:
            raise ValueError("Checksum mismatch, content corrupted")

        object_id = metadata.object_id
        object_size = len(data)
        if object_size > self.capacity_bytes:
            self.rejected_write_count += 1
            return CacheWriteResult(
                stored=False,
                evicted_object_ids=[],
                evicted_bytes=0,
                object_size_bytes=object_size,
            )

        existing = self.storage.pop(object_id, None)
        if existing is not None:
            self.current_size_bytes -= len(existing)

        self.metadata[object_id] = metadata

        evicted_object_ids: List[str] = []
        evicted_bytes = 0
        while self.current_size_bytes + object_size > self.capacity_bytes and self.storage:
            evicted_object_id, evicted_data = self.storage.popitem(last=False)
            self.current_size_bytes -= len(evicted_data)
            evicted_bytes += len(evicted_data)
            evicted_object_ids.append(evicted_object_id)
            self.metadata.pop(evicted_object_id, None)
            self.eviction_count += 1

        self.storage[object_id] = data
        self.current_size_bytes += object_size
        self.storage.move_to_end(object_id)

        return CacheWriteResult(
            stored=True,
            evicted_object_ids=evicted_object_ids,
            evicted_bytes=evicted_bytes,
            object_size_bytes=object_size,
        )

    def get(self, object_id: str) -> Optional[bytes]:
        data = self.storage.get(object_id)
        if data is None:
            self.miss_count += 1
            return None
        self.storage.move_to_end(object_id)
        self.hit_count += 1
        return data

    def get_metadata(self, object_id: str) -> Optional[ObjectMetadata]:
        metadata = self.metadata.get(object_id)
        if metadata is not None and object_id in self.storage:
            self.storage.move_to_end(object_id)
        return metadata

    def get_stats(self) -> Dict[str, int]:
        return {
            "capacity_bytes": self.capacity_bytes,
            "current_size_bytes": self.current_size_bytes,
            "object_count": len(self.storage),
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "eviction_count": self.eviction_count,
            "rejected_write_count": self.rejected_write_count,
        }
