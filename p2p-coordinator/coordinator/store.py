from typing import Dict, List, Set
from datetime import datetime, timedelta
import asyncio
from common.schemas import PeerInfo, ObjectMetadata, RegisterRequest

class Store:
    def __init__(self):
        # Maps peer_id -> PeerInfo
        self.peers: Dict[str, PeerInfo] = {}
        # Maps object_id -> Set of peer_ids
        self.index: Dict[str, Set[str]] = {}
        # Maps object_id -> ObjectMetadata (to store checksum etc)
        self.object_metadata: Dict[str, ObjectMetadata] = {}

    def register_peer(self, req: RegisterRequest) -> PeerInfo:
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
        if peer_id in self.peers:
            self.peers[peer_id].last_seen = datetime.now()

    def publish_object(self, peer_id: str, metadata: ObjectMetadata):
        if peer_id not in self.peers:
            # We could error here, but for simplicity let's just ignore or register empty
            return
        
        obj_id = metadata.object_id
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

        return [p.url for p in providers]

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
