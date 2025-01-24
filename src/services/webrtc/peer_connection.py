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