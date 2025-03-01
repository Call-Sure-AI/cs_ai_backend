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
        self.is_closed = False
        
    async def set_websocket(self, websocket):
        """Set the WebSocket connection for this peer"""
        self.websocket = websocket
        self.is_closed = False
        
    async def send_message(self, message: Dict[str, Any]):
        """Send a message through the peer's WebSocket"""
        if self.websocket and not self.is_closed:
            try:
                self.last_activity = datetime.utcnow()
                await self.websocket.send_json(message)
                self.message_count += 1
            except Exception as e:
                logger.error(f"Error sending message to peer {self.peer_id}: {str(e)}")
                self.is_closed = True
            
    async def close(self):
        """Close the peer connection"""
        if self.websocket and not self.is_closed:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket for peer {self.peer_id}: {str(e)}")
            finally:
                self.is_closed = True
            
    def is_active(self, timeout_seconds: int = 300) -> bool:
        """Check if the peer connection is active within timeout period"""
        if self.is_closed or not self.websocket:
            return False
        
        try:
            # Check FastAPI WebSocket client_state and application_state
            if hasattr(self.websocket, 'client_state') and self.websocket.client_state.name == "DISCONNECTED":
                return False
            if hasattr(self.websocket, 'application_state') and self.websocket.application_state.name == "DISCONNECTED":
                return False
        except Exception:
            # If attributes don't exist or we get an error, fall back to time-based check
            pass
            
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
            "is_connected": bool(self.websocket and not self.is_closed)
        }