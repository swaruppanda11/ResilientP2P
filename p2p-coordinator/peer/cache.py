import os
import hashlib
from typing import Dict, Optional
from common.schemas import ObjectMetadata

class Cache:
    def __init__(self):
        # Memory-based cache for simplicity in this project
        # In real world, use disk
        self.storage: Dict[str, bytes] = {}
        self.metadata: Dict[str, ObjectMetadata] = {}

    def put(self, metadata: ObjectMetadata, data: bytes):
        # Verify checksum before caching
        checksum = hashlib.sha256(data).hexdigest()
        if checksum != metadata.checksum:
            raise ValueError("Checksum mismatch, content corrupted")
        
        self.storage[metadata.object_id] = data
        self.metadata[metadata.object_id] = metadata

    def get(self, object_id: str) -> Optional[bytes]:
        return self.storage.get(object_id)

    def has(self, object_id: str) -> bool:
        return object_id in self.storage

    def get_metadata(self, object_id: str) -> Optional[ObjectMetadata]:
        return self.metadata.get(object_id)
