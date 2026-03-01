from typing import Dict, List, Set
from datetime import datetime, timedelta
from common.schemas import PeerInfo, ObjectMetadata, RegisterRequest


class StoreError(Exception):
    error_code = "STORE_ERROR"


class DuplicatePeerError(StoreError):
    error_code = "DUPLICATE_PEER"


class UnknownPeerError(StoreError):
    error_code = "UNKNOWN_PEER"


class InvalidPublishError(StoreError):
    error_code = "INVALID_PUBLISH"


class Store:
    def __init__(self, max_providers_per_lookup: int = 3):
        # Maps peer_id -> PeerInfo
        self.peers: Dict[str, PeerInfo] = {}
        # Maps object_id -> Set of peer_ids
        self.index: Dict[str, Set[str]] = {}
        # Maps object_id -> ObjectMetadata (to store checksum etc)
        self.object_metadata: Dict[str, ObjectMetadata] = {}
        self.max_providers_per_lookup = max_providers_per_lookup

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
        if existing_metadata and existing_metadata != metadata:
            raise InvalidPublishError(
                f"Object '{obj_id}' metadata conflicts with existing published metadata"
            )
        if obj_id not in self.index:
            self.index[obj_id] = set()
            self.object_metadata[obj_id] = metadata
            
        self.index[obj_id].add(peer_id)

    def get_providers(self, object_id: str, requesting_location: str) -> List[str]:
        if object_id not in self.index:
            return []

        peer_ids = self.index[object_id]
        providers = []
        
        for p_id in peer_ids:
            if p_id in self.peers:
                providers.append(self.peers[p_id])

        # Locality sorting:
        # Same location_id comes first
        providers.sort(key=lambda p: p.location_id != requesting_location)

        return [p.url for p in providers[: self.max_providers_per_lookup]]

    def get_stats(self) -> Dict[str, int]:
        return {
            "peer_count": len(self.peers),
            "object_count": len(self.index),
            "provider_entries": sum(len(peer_ids) for peer_ids in self.index.values()),
            "max_providers_per_lookup": self.max_providers_per_lookup,
        }

    def cleanup(self, timeout_seconds: int = 30):
        now = datetime.now()
        threshold = now - timedelta(seconds=timeout_seconds)
        
        dead_peers = [
            p_id for p_id, p_info in self.peers.items() 
            if p_info.last_seen < threshold
        ]
        
        for p_id in dead_peers:
            del self.peers[p_id]
            # Remove this peer from all index entries
            for obj_id in list(self.index.keys()):
                if p_id in self.index[obj_id]:
                    self.index[obj_id].remove(p_id)
                if not self.index[obj_id]:
                    del self.index[obj_id]
                    if obj_id in self.object_metadata:
                        del self.object_metadata[obj_id]
