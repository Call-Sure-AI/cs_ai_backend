# src/services/webrtc/__init__.py
from .manager import WebRTCManager
from .peer_connection import PeerConnection

__all__ = ['WebRTCManager', 'PeerConnection']

# src/services/webrtc/peer_connection.py
from typing import Optional, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class PeerConnection:
    def __init__(self, peer_id: str, company_info: dict):
        self.peer_id = peer_id
        self.company_id = str(company_info['id'])
        self.company_info = company_info
        self.connected_at = datetime.utcnow()
        self.last_activity = self.connected_at
        self.websocket = None
        self.message_count = 0
        
    async def set_websocket(self, websocket):
        """Set the WebSocket connection for this peer"""
        self.websocket = websocket
        
    async def send_message(self, message: Dict[str, Any]):
        """Send a message through the peer's WebSocket"""
        if self.websocket and not self.websocket.closed:
            self.last_activity = datetime.utcnow()
            await self.websocket.send_json(message)
            self.message_count += 1
            
    async def close(self):
        """Close the peer connection"""
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
            
    def is_active(self, timeout_seconds: int = 300) -> bool:
        """Check if the peer connection is active within timeout period"""
        if not self.websocket or self.websocket.closed:
            return False
        
        time_diff = (datetime.utcnow() - self.last_activity).total_seconds()
        return time_diff < timeout_seconds

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            "peer_id": self.peer_id,
            "company_id": self.company_id,
            "connected_at": self.connected_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "message_count": self.message_count,
            "is_connected": bool(self.websocket and not self.websocket.closed)
        }

# src/services/webrtc/manager.py
from typing import Dict, Set, Optional
import logging
from datetime import datetime
import asyncio
from sqlalchemy.orm import Session
from fastapi import WebSocket

from .peer_connection import PeerConnection
from services.qdrant_embedding import QdrantService
from managers.agent_manager import AgentManager

logger = logging.getLogger(__name__)

class WebRTCManager:
    def __init__(self):
        self.peers: Dict[str, PeerConnection] = {}  # peer_id -> PeerConnection
        self.company_peers: Dict[str, Set[str]] = {}  # company_id -> set of peer_ids
        self.agent_manager: Optional[AgentManager] = None
        self.vector_store: Optional[QdrantService] = None
        
    def initialize_services(self, db: Session, vector_store: QdrantService):
        """Initialize required services"""
        self.vector_store = vector_store
        if not self.agent_manager:
            self.agent_manager = AgentManager(db, vector_store)
            logger.info("Agent manager initialized")
            
    async def register_peer(self, peer_id: str, company_info: dict, websocket: WebSocket) -> PeerConnection:
        """Register a new peer connection"""
        company_id = str(company_info['id'])
        
        # Create new peer connection
        peer = PeerConnection(peer_id, company_info)
        await peer.set_websocket(websocket)
        
        # Store peer references
        self.peers[peer_id] = peer
        if company_id not in self.company_peers:
            self.company_peers[company_id] = set()
        self.company_peers[company_id].add(peer_id)
        
        logger.info(f"Registered peer {peer_id} for company {company_id}")
        return peer
        
    async def unregister_peer(self, peer_id: str):
        """Remove a peer connection"""
        if peer_id in self.peers:
            peer = self.peers[peer_id]
            company_id = peer.company_id
            
            # Close peer connection
            await peer.close()
            
            # Remove peer references
            del self.peers[peer_id]
            if company_id in self.company_peers:
                self.company_peers[company_id].discard(peer_id)
                if not self.company_peers[company_id]:
                    del self.company_peers[company_id]
                    
            logger.info(f"Unregistered peer {peer_id}")
            
    async def relay_signal(self, from_peer_id: str, to_peer_id: str, signal_data: dict):
        """Relay WebRTC signaling message between peers"""
        if to_peer_id in self.peers:
            to_peer = self.peers[to_peer_id]
            await to_peer.send_message({
                'type': 'signal',
                'from_peer': from_peer_id,
                'data': signal_data
            })
            logger.debug(f"Relayed signal from {from_peer_id} to {to_peer_id}")
            
    async def broadcast_to_company(self, company_id: str, message: dict):
        """Broadcast message to all peers in a company"""
        if company_id in self.company_peers:
            for peer_id in self.company_peers[company_id]:
                if peer_id in self.peers:
                    await self.peers[peer_id].send_message(message)
                    
    async def process_streaming_message(self, peer_id: str, message_data: dict):
        """Process streaming message through agent manager"""
        if peer_id in self.peers and self.agent_manager:
            peer = self.peers[peer_id]
            company_id = peer.company_id
            
            response_stream = await self.agent_manager.process_message_stream(
                company_id, message_data
            )
            
            async for response in response_stream:
                await peer.send_message({
                    'type': 'stream',
                    'data': response
                })
                
    def get_company_peers(self, company_id: str) -> list:
        """Get list of active peers for a company"""
        return list(self.company_peers.get(company_id, set()))
        
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        return {
            "total_peers": len(self.peers),
            "total_companies": len(self.company_peers),
            "peers_by_company": {
                company_id: len(peers) 
                for company_id, peers in self.company_peers.items()
            },
            "peer_details": [
                peer.get_stats() for peer in self.peers.values()
            ]
        }