# src/routes/webrtc_handlers.py
from fastapi import APIRouter, WebSocket, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any
import logging
import json
from datetime import datetime
import asyncio
import time

from database.config import get_db
from services.webrtc import WebRTCManager
from services.qdrant_embedding import QdrantService
from utils.logger import setup_logging
from config.settings import settings
from database.models import Company

# Initialize router and logging
router = APIRouter()
setup_logging()
logger = logging.getLogger(__name__)

# Initialize services
vector_store = QdrantService(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
webrtc_manager = WebRTCManager()

@router.websocket("/signal/{peer_id}/{company_api_key}")
async def signaling_endpoint(
    websocket: WebSocket,
    peer_id: str,
    company_api_key: str,
    db: Session = Depends(get_db)
):
    """WebRTC signaling endpoint handler with detailed timing logs"""
    connection_start = time.time()
    
    try:
        # Validate company before accepting connection
        company_validation_start = time.time()
        company = db.query(Company).filter_by(api_key=company_api_key).first()
        company_validation_time = time.time() - company_validation_start
        logger.info(f"Company validation took {company_validation_time:.3f}s")
        
        if not company:
            logger.warning(f"Invalid API key: {company_api_key}")
            await websocket.close(code=4001)
            return
            
        logger.info(f"Company validated: {company.name}")
        
        # Initialize services if needed
        webrtc_manager.initialize_services(db, vector_store)
        
        # Set up company info
        company_info = {
            "id": company.id,
            "name": company.name,
            "settings": company.settings
        }
        
        # Accept WebSocket connection
        connect_start = time.time()
        await websocket.accept()
        peer = await webrtc_manager.register_peer(peer_id, company_info, websocket)
        connect_time = time.time() - connect_start
        logger.info(f"WebRTC connection setup took {connect_time:.3f}s")
        
        # Send ICE servers configuration
        await peer.send_message({
            'type': 'config',
            'ice_servers': [
                {'urls': ['stun:stun.l.google.com:19302']},
                # Add TURN servers here for production
            ]
        })
        
        # Main message loop
        try:
            while True:
                loop_start = time.time()
                try:
                    # Message reception with timeout
                    receive_start = time.time()
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=settings.WS_HEARTBEAT_INTERVAL
                    )
                    receive_time = time.time() - receive_start
                    
                    # Process received message
                    process_start = time.time()
                    message_type = data.get('type')
                    
                    if message_type == 'signal':
                        # Handle WebRTC signaling
                        to_peer = data.get('to_peer')
                        if to_peer:
                            await webrtc_manager.relay_signal(
                                peer_id, to_peer, data.get('data', {})
                            )
                    elif message_type == 'message':
                        # Handle streaming messages
                        await webrtc_manager.process_streaming_message(peer_id, data)
                    elif message_type == 'ping':
                        await peer.send_message({'type': 'pong'})
                        
                    process_time = time.time() - process_start
                    logger.info(f"Message processing took {process_time:.3f}s")
                    
                except asyncio.TimeoutError:
                    ping_start = time.time()
                    await peer.send_message({"type": "ping"})
                    logger.debug(f"Heartbeat ping sent in {time.time() - ping_start:.3f}s")
                    continue
                    
                loop_time = time.time() - loop_start
                logger.info(f"Complete message cycle took {loop_time:.3f}s")
                
        except Exception as e:
            logger.error(f"Error in message loop: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in signaling endpoint: {str(e)}")
        if not websocket.closed:
            await websocket.close(code=1011)
            
    finally:
        # Clean up peer connection
        cleanup_start = time.time()
        await webrtc_manager.unregister_peer(peer_id)
        cleanup_time = time.time() - cleanup_start
        
        total_time = time.time() - connection_start
        logger.info(
            f"Connection ended for peer {peer_id}. "
            f"Duration: {total_time:.3f}s, "
            f"Cleanup time: {cleanup_time:.3f}s"
        )

@router.get("/peers/{company_api_key}")
async def get_active_peers(
    company_api_key: str,
    db: Session = Depends(get_db)
):
    """Get list of active peers for a company"""
    company = db.query(Company).filter_by(api_key=company_api_key).first()
    if not company:
        raise HTTPException(status_code=401, detail="Invalid API key")
        
    company_id = str(company.id)
    active_peers = webrtc_manager.get_company_peers(company_id)
    return {
        "company_id": company_id,
        "active_peers": active_peers
    }

@router.get("/stats")
async def get_webrtc_stats():
    """Get WebRTC system statistics"""
    return webrtc_manager.get_stats()

@router.websocket("/health")
async def health_check(websocket: WebSocket):
    """Health check endpoint"""
    try:
        await websocket.accept()
        await websocket.send_json({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat()
        })
    finally:
        await websocket.close()