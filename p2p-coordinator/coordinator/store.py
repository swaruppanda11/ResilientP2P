from typing import Dict, List, Set
from datetime import datetime, timedelta, timezone
from common.schemas import PeerInfo, ObjectMetadata, PeerLoadStats, RegisterRequest


class StoreError(Exception):
    error_code = "STORE_ERROR"


class DuplicatePeerError(StoreError):
    error_code = "DUPLICATE_PEER"


class UnknownPeerError(StoreError):
    error_code = "UNKNOWN_PEER"


class InvalidPublishError(StoreError):
    error_code = "INVALID_PUBLISH"


class Store:
    def __init__(
        self,
        max_providers_per_lookup: int = 3,
        provider_selection_policy: str = "locality_then_load",
    ):
        # Maps peer_id -> PeerInfo
        self.peers: Dict[str, PeerInfo] = {}
        # Maps object_id -> Set of peer_ids
        self.index: Dict[str, Set[str]] = {}
        # Maps object_id -> ObjectMetadata (to store checksum etc)
        self.object_metadata: Dict[str, ObjectMetadata] = {}
        # Maps object_id -> peer_id -> version, so lookups can avoid old-version providers.
        self.object_provider_versions: Dict[str, Dict[str, str]] = {}
        # Maps peer_id -> lightweight load stats used by provider selection
        self.peer_loads: Dict[str, PeerLoadStats] = {}
        self.max_providers_per_lookup = max_providers_per_lookup
        self.provider_selection_policy = provider_selection_policy

    def register_peer(self, req: RegisterRequest) -> PeerInfo:
        existing_peer = self.peers.get(req.peer_id)
        if existing_peer:
            raise DuplicatePeerError(f"Peer '{req.peer_id}' is already registered")

        # Construct URL from host and port
        url = f"http://{req.host}:{req.port}"
        peer = PeerInfo(
            peer_id=req.peer_id,
            url=url,
            location_id=req.location_id,
            last_seen=datetime.now()
        )
        self.peers[req.peer_id] = peer
        self.peer_loads[req.peer_id] = PeerLoadStats(peer_id=req.peer_id)
        return peer

    def heartbeat(self, peer_id: str):
        if peer_id not in self.peers:
            raise UnknownPeerError(f"Peer '{peer_id}' is not registered")
        self.peers[peer_id].last_seen = datetime.now()

    def publish_object(self, peer_id: str, metadata: ObjectMetadata):
        if peer_id not in self.peers:
            raise UnknownPeerError(f"Peer '{peer_id}' is not registered")

        obj_id = metadata.object_id
        existing_metadata = self.object_metadata.get(obj_id)
        if existing_metadata and self._metadata_conflicts(existing_metadata, metadata):
            raise InvalidPublishError(
                f"Object '{obj_id}' metadata conflicts with existing published metadata"
            )
        if obj_id not in self.index:
            self.index[obj_id] = set()
        if obj_id not in self.object_provider_versions:
            self.object_provider_versions[obj_id] = {}
        self.object_metadata[obj_id] = metadata
            
        self.index[obj_id].add(peer_id)
        self.object_provider_versions[obj_id][peer_id] = metadata.version

    def report_transfer(self, peer_id: str, object_id: str, bytes_served: int) -> PeerLoadStats:
        if peer_id not in self.peers:
            raise UnknownPeerError(f"Peer '{peer_id}' is not registered")

        existing = self.peer_loads.get(peer_id, PeerLoadStats(peer_id=peer_id))
        update = {
            "total_upload_requests": existing.total_upload_requests + 1,
            "total_upload_bytes": existing.total_upload_bytes + bytes_served,
            "last_transfer_at": datetime.now(),
        }
        if hasattr(existing, "model_copy"):
            updated = existing.model_copy(update=update)
        else:
            updated = existing.copy(update=update)
        self.peer_loads[peer_id] = updated
        return updated

    def get_providers(
        self,
        object_id: str,
        requesting_location: str,
        version: str | None = None,
    ) -> List[str]:
        if object_id not in self.index:
            return []
        metadata = self.get_object_metadata(object_id, version=version)
        if metadata is None:
            return []

        requested_version = version or metadata.version
        peer_versions = self.object_provider_versions.get(object_id, {})
        peer_ids = [
            p_id
            for p_id in self.index[object_id]
            if peer_versions.get(p_id, metadata.version) == requested_version
        ]
        providers = []
        
        for p_id in peer_ids:
            if p_id in self.peers:
                providers.append(self.peers[p_id])

        providers.sort(key=lambda peer: self._provider_sort_key(peer, requesting_location))

        return [p.url for p in providers[: self.max_providers_per_lookup]]

    def get_object_metadata(self, object_id: str, version: str | None = None):
        metadata = self.object_metadata.get(object_id)
        if metadata is not None and self._metadata_expired(metadata):
            self._remove_object(object_id)
            return None
        if version is not None and metadata is not None and metadata.version != version:
            return None
        return metadata

    def invalidate_object(self, object_id: str):
        peer_ids = set(self.index.get(object_id, set()))
        provider_urls = sorted(
            self.peers[p_id].url
            for p_id in peer_ids
            if p_id in self.peers
        )
        removed_provider_entries = len(peer_ids)
        self._remove_object(object_id)
        return provider_urls, removed_provider_entries

    def invalidate_prefix(self, prefix: str):
        object_ids = [
            object_id
            for object_id in self.object_metadata.keys()
            if object_id.startswith(prefix)
        ]
        provider_urls = set()
        removed_provider_entries = 0
        for object_id in object_ids:
            peer_ids = set(self.index.get(object_id, set()))
            removed_provider_entries += len(peer_ids)
            for peer_id in peer_ids:
                if peer_id in self.peers:
                    provider_urls.add(self.peers[peer_id].url)
            self._remove_object(object_id)
        return sorted(provider_urls), removed_provider_entries, object_ids

    def get_stats(self) -> Dict[str, int]:
        return {
            "peer_count": len(self.peers),
            "object_count": len(self.index),
            "provider_entries": sum(len(peer_ids) for peer_ids in self.index.values()),
            "max_providers_per_lookup": self.max_providers_per_lookup,
            "provider_selection_policy": self.provider_selection_policy,
            "total_upload_requests": sum(load.total_upload_requests for load in self.peer_loads.values()),
            "total_upload_bytes": sum(load.total_upload_bytes for load in self.peer_loads.values()),
            "peer_loads": [
                load.model_dump() if hasattr(load, "model_dump") else load.dict()
                for load in self.peer_loads.values()
            ],
        }

    def _provider_sort_key(self, peer: PeerInfo, requesting_location: str):
        load = self.peer_loads.get(peer.peer_id, PeerLoadStats(peer_id=peer.peer_id))
        locality_key = peer.location_id != requesting_location
        if self.provider_selection_policy == "locality_only":
            return (locality_key, peer.peer_id)
        return (
            locality_key,
            load.total_upload_requests,
            load.total_upload_bytes,
            peer.peer_id,
        )

    def _metadata_conflicts(self, existing: ObjectMetadata, incoming: ObjectMetadata) -> bool:
        if existing.version != incoming.version:
            return False
        return (
            existing.checksum != incoming.checksum
            or existing.size_bytes != incoming.size_bytes
            or existing.cacheability != incoming.cacheability
        )

    def _metadata_expired(self, metadata: ObjectMetadata) -> bool:
        if metadata.cacheability == "immutable":
            return False
        if metadata.expires_at is None:
            return metadata.cacheability == "dynamic"
        expires_at = metadata.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at

    def _remove_object(self, object_id: str) -> None:
        self.index.pop(object_id, None)
        self.object_metadata.pop(object_id, None)
        self.object_provider_versions.pop(object_id, None)

    def cleanup(self, timeout_seconds: int = 30):
        now = datetime.now()
        threshold = now - timedelta(seconds=timeout_seconds)
        
        dead_peers = [
            p_id for p_id, p_info in self.peers.items() 
            if p_info.last_seen < threshold
        ]
        
        for p_id in dead_peers:
            del self.peers[p_id]
            self.peer_loads.pop(p_id, None)
            # Remove this peer from all index entries
            for obj_id in list(self.index.keys()):
                if p_id in self.index[obj_id]:
                    self.index[obj_id].remove(p_id)
                    self.object_provider_versions.get(obj_id, {}).pop(p_id, None)
                if not self.index[obj_id]:
                    del self.index[obj_id]
                    self.object_provider_versions.pop(obj_id, None)
                    if obj_id in self.object_metadata:
                        del self.object_metadata[obj_id]

        for obj_id, metadata in list(self.object_metadata.items()):
            if self._metadata_expired(metadata):
                self._remove_object(obj_id)
