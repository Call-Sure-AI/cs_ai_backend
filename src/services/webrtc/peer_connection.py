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
                # Check if websocket is still open before sending
                if self.websocket_is_closed():
                    logger.warning(f"Cannot send message to closed websocket for peer {self.peer_id}")
                    self.is_closed = True
                    return
                    
                self.last_activity = datetime.utcnow()
                await self.websocket.send_json(message)
                self.message_count += 1
            except Exception as e:
                logger.error(f"Error sending message to peer {self.peer_id}: {str(e)}")
                self.is_closed = True
    
    def websocket_is_closed(self) -> bool:
        """Check if websocket is closed with proper error handling"""
        try:
            return (
                not self.websocket or
                self.websocket.client_state.name == "DISCONNECTED" or
                self.websocket.application_state.name == "DISCONNECTED"
            )
        except AttributeError:
            # If we can't check the state, assume it's closed to be safe
            return True
            
    async def close(self):
        """Close the peer connection"""
        if self.websocket and not self.is_closed:
            try:
                # Only try to close the WebSocket if it's not already closed
                if not self.websocket_is_closed():
                    await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket for peer {self.peer_id}: {str(e)}")
            finally:
                self.is_closed = True
                self.websocket = None  # Clear the reference
            
    def is_active(self, timeout_seconds: int = 300) -> bool:
        """Check if the peer connection is active within timeout period"""
        if self.is_closed or not self.websocket:
            return False
        
        # Use websocket_is_closed helper
        if self.websocket_is_closed():
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
            "is_connected": not (self.is_closed or self.websocket_is_closed() if self.websocket else True)
        }