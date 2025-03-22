# src/services/webrtc/manager.py
from typing import Dict, Set, Optional, Any
import logging
from datetime import datetime
import asyncio
import os
from sqlalchemy.orm import Session
from fastapi import WebSocket

from .peer_connection import PeerConnection
from .audio_handler import WebRTCAudioHandler
from services.vector_store.qdrant_service import QdrantService
from managers.agent_manager import AgentManager
from managers.connection_manager import ConnectionManager
from config.settings import settings
import time

logger = logging.getLogger(__name__)

class WebRTCManager:
    def __init__(self):
        self.peers: Dict[str, PeerConnection] = {}  # peer_id -> PeerConnection
        self.company_peers: Dict[str, Set[str]] = {}  # company_id -> set of peer_ids
        self.agent_manager: Optional[AgentManager] = None
        self.connection_manager: Optional[ConnectionManager] = None
        self.vector_store: Optional[QdrantService] = None
        
        # Initialize audio handler
        audio_save_path = os.path.join(settings.MEDIA_ROOT, 'audio') if hasattr(settings, 'MEDIA_ROOT') else None
        self.audio_handler = WebRTCAudioHandler(audio_save_path=audio_save_path)
        logger.info("WebRTC audio handler initialized")
        
    def initialize_services(self, db: Session, vector_store: QdrantService):
        """Initialize required services"""
        self.vector_store = vector_store
        
        # Initialize agent manager if not already present
        if not self.agent_manager:
            self.agent_manager = AgentManager(db, vector_store)
            logger.info("Agent manager initialized")
            
        # Initialize connection manager if not already present
        if not self.connection_manager:
            self.connection_manager = ConnectionManager(db, vector_store)
            logger.info("Connection manager initialized")
            
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
        
        # If this is a client peer (not a WebRTC signaling peer),
        # register with connection manager as well
        if peer_id.startswith('client_') and self.connection_manager:
            await self.connection_manager.connect(websocket, peer_id)
            self.connection_manager.client_companies[peer_id] = company_info
            
        logger.info(f"Registered peer {peer_id} for company {company_id}")
        return peer
        
    async def unregister_peer(self, peer_id: str):
        """Remove a peer connection"""
        if peer_id in self.peers:
            peer = self.peers[peer_id]
            company_id = peer.company_id
            
            # Close any active audio streams for this peer
            try:
                await self.audio_handler.end_audio_stream(peer_id)
            except Exception as e:
                logger.warning(f"Error ending audio stream during peer unregistration: {str(e)}")
            
            # Unregister from connection manager if it's a client peer
            if peer_id.startswith('client_') and self.connection_manager:
                self.connection_manager.disconnect(peer_id)
            
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
    
    async def handle_audio_message(self, peer_id: str, message_data: dict) -> dict:
        """Handle audio-related messages"""
        if peer_id not in self.peers:
            logger.warning(f"Audio message received for unknown peer: {peer_id}")
            return {"status": "error", "error": "Unknown peer"}
        
        action = message_data.get("action", "")
        
        if action == "start_stream":
            # Start a new audio stream
            result = await self.audio_handler.start_audio_stream(
                peer_id, message_data.get("metadata", {})
            )
            logger.info(f"Started audio stream for peer {peer_id}: {result}")
            return result
            
        elif action == "audio_chunk":
            # Process an audio chunk
            result = await self.audio_handler.process_audio_chunk(
                peer_id, message_data.get("chunk_data", {})
            )
            # Only log at debug level to avoid log spam
            logger.debug(f"Processed audio chunk for peer {peer_id}")
            return result
            
        elif action == "end_stream":
            # End an audio stream
            result = await self.audio_handler.end_audio_stream(
                peer_id, message_data.get("metadata", {})
            )
            logger.info(f"Ended audio stream for peer {peer_id}: {result}")
            return result
            
        else:
            logger.warning(f"Unknown audio action: {action}")
            return {"status": "error", "error": f"Unknown action: {action}"}
                    
    async def process_message(self, peer_id: str, message_data: dict):
        """Process general messages from peers"""
        if peer_id in self.peers:
            message_type = message_data.get("type", "")
            
            if message_type == "audio":
                # Handle audio-specific messages
                result = await self.handle_audio_message(peer_id, message_data)
                
                # Send result back to the peer
                peer = self.peers[peer_id]
                await peer.send_message({
                    "type": "audio_response",
                    "data": result
                })
                
            elif message_type == "message":
                # Handle streaming text messages through connection manager
                await self.process_streaming_message(peer_id, message_data)
                
    async def process_streaming_message(self, peer_id: str, message_data: dict, agent_id: Optional[str] = None):
        """Process streaming message using ConnectionManager"""
        try:
            if peer_id not in self.peers:
                logger.warning(f"Message received for unknown peer: {peer_id}")
                return
                
            peer = self.peers[peer_id]
            
            # Check if we have a connection manager
            if not self.connection_manager:
                logger.error("Connection manager not initialized")
                await peer.send_message({
                    "type": "error",
                    "message": "Service not properly initialized"
                })
                return
                
            # Map peer to client ID if it's not already a client ID
            client_id = peer_id
            # if not client_id.startswith('client_'):
            #     # Generate a temporary client ID if we got a message from a non-client peer
            #     client_id = f"client_{int(time.time() * 1000)}"
            #     # Register the websocket with connection manager
            #     await self.connection_manager.connect(peer.websocket, client_id)
            #     self.connection_manager.client_companies[client_id] = peer.company_info
            #     logger.info(f"Created temporary client ID {client_id} for peer {peer_id}")
                
            # Initialize agent resources if needed
            company_id = peer.company_id
            
            # Check if the client already has agent resources
            if client_id not in self.connection_manager.agent_resources:
                # Get base agent
                if not agent_id:
                    base_agent = await self.agent_manager.get_base_agent(company_id)
                    if not base_agent:
                        logger.error(f"No base agent found for company {company_id}")
                        await peer.send_message({
                            "type": "error",
                            "message": "No agent available"
                        })
                        return
                        
                    # Initialize agent resources
                    success = await self.connection_manager.initialize_agent_resources(
                        client_id,
                        company_id,
                        base_agent
                    )
                else:  
                    logger.info(f"Agent ID: {agent_id}, type: {type(agent_id)}")
                    agent = {
                        'id': agent_id
                    }
                    success = await self.connection_manager.initialize_agent_resources(
                        client_id,
                        company_id,
                        agent
                    )
                
                if not success:
                    logger.error(f"Failed to initialize agent resources for {client_id}")
                    await peer.send_message({
                        "type": "error",
                        "message": "Failed to initialize agent resources"
                    })
                    return
                    
                # Set active agent
                self.connection_manager.active_agents[client_id] = base_agent['id']
                    
            # Process the message using connection manager
            await self.connection_manager.process_streaming_message(client_id, message_data)
            
        except Exception as e:
            logger.error(f"Error processing message stream: {str(e)}", exc_info=True)
            if peer_id in self.peers:
                peer = self.peers[peer_id]
                await peer.send_message({
                    "type": "error",
                    "message": f"Error processing message: {str(e)}"
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
            ],
            "audio_stats": self.audio_handler.get_stats()
        }