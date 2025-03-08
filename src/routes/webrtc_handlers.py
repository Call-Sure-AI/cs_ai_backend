# src/routes/webrtc_handlers.py
from fastapi import APIRouter, WebSocket, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging
import json
from datetime import datetime
import asyncio
import time

from services.speech.stt_service import SpeechToTextService
from database.config import get_db
from services.webrtc.manager import WebRTCManager
from services.vector_store.qdrant_service import QdrantService
from managers.connection_manager import ConnectionManager
from utils.logger import setup_logging
from config.settings import settings
from database.models import Company, Agent
import uuid

# Initialize router and logging
router = APIRouter()
setup_logging()
logger = logging.getLogger(__name__)

# Initialize services
vector_store = QdrantService()
webrtc_manager = WebRTCManager()

def initialize_app(app):
    """Initialize app state"""
    connection_manager = ConnectionManager(next(get_db()), vector_store)
    app.state.connection_manager = connection_manager
    app.state.webrtc_manager = webrtc_manager
    
    # Link the webrtc_manager to the connection_manager
    webrtc_manager.connection_manager = connection_manager
    
    logger.info("Application initialized with connection and WebRTC managers")

# @router.websocket("/signal/{peer_id}/{company_api_key}/{agent_id}")
# async def signaling_endpoint(
#     websocket: WebSocket,
#     peer_id: str,
#     company_api_key: str,
#     agent_id: str,
#     db: Session = Depends(get_db)
# ):
#     """WebRTC signaling endpoint handler with detailed timing logs"""
#     connection_start = time.time()
#     websocket_closed = False
#     peer = None
    
#     try:
#         # Initialize the webrtc manager with the connection manager if not already set
#         if not webrtc_manager.connection_manager and hasattr(websocket.app.state, 'connection_manager'):
#             webrtc_manager.connection_manager = websocket.app.state.connection_manager
#             logger.info("WebRTC manager linked to connection manager")
        
#         # Validate company before accepting connection
#         company_validation_start = time.time()
#         company = db.query(Company).filter_by(api_key=company_api_key).first()
#         company_validation_time = time.time() - company_validation_start
#         logger.info(f"Company validation took {company_validation_time:.3f}s")
        
#         if not company:
#             logger.warning(f"Invalid API key: {company_api_key}")
#             try:
#                 await websocket.close(code=4001)
#                 websocket_closed = True
#             except Exception as e:
#                 logger.error(f"Error closing websocket: {str(e)}")
#             return
            
#         logger.info(f"Company validated: {company.name}")
        
#         # Initialize services if needed
#         webrtc_manager.initialize_services(db, vector_store)
        
#         # Set up company info
#         company_info = {
#             "id": company.id,
#             "name": company.name,
#             "settings": company.settings
#         }
        
#         # Accept WebSocket connection
#         connect_start = time.time()
#         try:
#             await websocket.accept()
#             peer = await webrtc_manager.register_peer(peer_id, company_info, websocket)
#             connect_time = time.time() - connect_start
#             logger.info(f"WebRTC connection setup took {connect_time:.3f}s")
#         except Exception as e:
#             logger.error(f"Error accepting connection: {str(e)}")
#             websocket_closed = True
#             return
        
#         # Send ICE servers configuration
#         try:
#             await peer.send_message({
#                 'type': 'config',
#                 'ice_servers': [
#                     {'urls': ['stun:stun.l.google.com:19302']},
#                     # Add TURN servers here for production
#                 ]
#             })
#         except Exception as e:
#             logger.error(f"Error sending ICE config: {str(e)}")
#             websocket_closed = True
#             return
        
#         # Main message loop
#         while not websocket_closed:
#             loop_start = time.time()
#             message_type = None  # Initialize message_type at the start of each loop
            
#             try:
#                 # Message reception with timeout
#                 receive_start = time.time()
#                 data = await asyncio.wait_for(
#                     websocket.receive_json(),
#                     timeout=settings.WS_HEARTBEAT_INTERVAL
#                 )
#                 receive_time = time.time() - receive_start
                
#                 # Process received message
#                 process_start = time.time()
#                 message_type = data.get('type')
                
#                 if message_type == 'signal':
#                     # Handle WebRTC signaling
#                     to_peer = data.get('to_peer')
#                     if to_peer:
#                         await webrtc_manager.relay_signal(
#                             peer_id, to_peer, data.get('data', {})
#                         )
#                 elif message_type == 'audio':
#                     # Handle audio messages
#                     result = await webrtc_manager.handle_audio_message(peer_id, data)
#                     # Send result back to the peer
#                     await peer.send_message({
#                         "type": "audio_response",
#                         "data": result
#                     })
#                 elif message_type == 'message':
#                     # Handle streaming messages directly using webrtc_manager
#                     await webrtc_manager.process_streaming_message(peer_id, data)
#                 elif message_type == 'ping':
#                     await peer.send_message({'type': 'pong'})
                    
#                 process_time = time.time() - process_start
                
#                 # Only log detailed timing for non-audio messages to reduce log volume
#                 if message_type and message_type != 'audio' or (message_type == 'audio' and data.get('action') != 'audio_chunk'):
#                     logger.info(f"Message processing took {process_time:.3f}s for type {message_type}")
                
#                 # Only log complete cycle for non-audio-chunk messages to reduce log volume
#                 if message_type and message_type != 'audio' or (message_type == 'audio' and data.get('action') != 'audio_chunk'):
#                     loop_time = time.time() - loop_start
#                     logger.info(f"Complete message cycle took {loop_time:.3f}s")
                
#             except asyncio.TimeoutError:
#                 # Send heartbeat
#                 try:
#                     ping_start = time.time()
#                     await peer.send_message({"type": "ping"})
#                     logger.debug(f"Heartbeat ping sent in {time.time() - ping_start:.3f}s")
#                 except Exception as e:
#                     logger.error(f"Error sending heartbeat: {str(e)}")
#                     websocket_closed = True
#                     break
#             except Exception as e:
#                 logger.error(f"Error in message processing: {str(e)}")
#                 websocket_closed = True
#                 break
            
#     except Exception as e:
#         logger.error(f"Error in signaling endpoint: {str(e)}")
#     finally:
#         # Clean up peer connection
#         try:
#             cleanup_start = time.time()
#             await webrtc_manager.unregister_peer(peer_id)
#             cleanup_time = time.time() - cleanup_start
            
#             total_time = time.time() - connection_start
#             logger.info(
#                 f"Connection ended for peer {peer_id}. "
#                 f"Duration: {total_time:.3f}s, "
#                 f"Cleanup time: {cleanup_time:.3f}s"
#             )
#         except Exception as e:
#             logger.error(f"Error during cleanup: {str(e)}")

async def handle_twilio_media_stream(websocket: WebSocket, peer_id: str, company_api_key: str, agent_id: str, db: Session):
    """Handler for Twilio Media Streams within WebRTC signaling endpoint"""
    connection_id = str(uuid.uuid4())[:8]
    message_count = 0
    audio_chunks = 0
    call_sid = None
    connected = False
    client_id = peer_id
    websocket_closed = False
    
    # Speech recognition variables
    stt_service = SpeechToTextService()
    silence_threshold = 3.0  # 3 seconds of silence indicates end of user speech
    last_transcription_time = time.time()
    is_collecting_audio = False
    is_processing = False
    
    try:
        logger.info(f"[{connection_id}] Handling Twilio Media Stream for {peer_id}")
        
        # Get connection manager from app state
        if not webrtc_manager.connection_manager and hasattr(websocket.app.state, 'connection_manager'):
            webrtc_manager.connection_manager = websocket.app.state.connection_manager
            logger.info(f"[{connection_id}] WebRTC manager linked to connection manager")
        
        # Initialize resources
        connection_manager = webrtc_manager.connection_manager
        if not connection_manager:
            logger.error(f"[{connection_id}] Connection manager not found in app state!")
            await websocket.close(code=1011)
            websocket_closed = True
            return
            
        # Initialize company for Twilio calls
        company = db.query(Company).filter_by(api_key=company_api_key).first()
        if not company:
            logger.error(f"[{connection_id}] Company not found for API key: {company_api_key}")
            await websocket.close(code=1011)
            websocket_closed = True
            return
            
        # Set company info from the database
        company_info = {
            "id": company.id,
            "name": company.name
        }
        
        connection_manager.client_companies[client_id] = company_info
        
        # Connect client to manager
        await connection_manager.connect(websocket, client_id)
        logger.info(f"[{connection_id}] Client {client_id} connected to manager")
        
        # Initialize agent resources
        agent_record = db.query(Agent).filter_by(id=agent_id).first()
        if not agent_record:
            logger.error(f"[{connection_id}] Agent not found with ID: {agent_id}")
            await websocket.close(code=1011)
            websocket_closed = True
            return
            
        agent = {
            "id": agent_record.id,
            "name": agent_record.name,
            "type": agent_record.type,
            "prompt": agent_record.prompt,
            "confidence_threshold": agent_record.confidence_threshold
        }
        
        # Initialize agent resources for this client
        success = await connection_manager.initialize_agent_resources(client_id, company_info["id"], agent)
        if not success:
            logger.error(f"[{connection_id}] Failed to initialize agent resources")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        # Define the callback function to handle transcriptions
        async def handle_transcription(session_id, text):
            nonlocal last_transcription_time
            
            logger.info(f"[{connection_id}] Received transcription: {text}")
            last_transcription_time = time.time()
            
            # Process using connection manager
            message_data = {
                "type": "message",
                "message": text,
                "source": "twilio"
            }
            
            # Run as a separate task to avoid blocking
            asyncio.create_task(
                connection_manager.process_streaming_message(client_id, message_data)
            )
        
        # Main message processing loop
        while not websocket_closed:
            try:
                # Try to receive message with a timeout for silence detection
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                message_count += 1
                
                current_time = time.time()
                
                if 'bytes' in message:
                    # Binary data (audio chunks)
                    audio_data = message['bytes']
                    audio_chunks += 1
                    
                    # Process the audio through STT service
                    await stt_service.process_audio_chunk(client_id, audio_data, handle_transcription)
                    
                    # Log occasionally to reduce verbosity
                    if audio_chunks == 1 or audio_chunks % 100 == 0:
                        logger.info(f"[{connection_id}] Processed audio chunk #{audio_chunks}, size: {len(audio_data)} bytes")
                
                elif 'text' in message:
                    # Parse text messages (control messages)
                    text_data = message['text']
                    
                    try:
                        data = json.loads(text_data)
                        event = data.get('event')
                        
                        if event == 'start':
                            # Extract stream and call information
                            stream_sid = data.get('streamSid')
                            call_sid = data.get('start', {}).get('callSid') or data.get('callSid')
                            
                            if call_sid:
                                logger.info(f"[{connection_id}] Start event for call SID: {call_sid}")
                            
                            # CRITICAL: Must respond to start event with connected message
                            logger.info(f"[{connection_id}] START event received: {json.dumps(data)}")
                            
                            await websocket.send_text(json.dumps({
                                "event": "connected",
                                "protocol": "websocket",
                                "version": "1.0.0"
                            }))
                            logger.info(f"[{connection_id}] Sent connected response")
                            connected = True
                            
                            # Add a small delay to stabilize the connection
                            await asyncio.sleep(0.5)
                            
                            # Send welcome message
                            welcome_data = {
                                "type": "message",
                                "message": "__SYSTEM_WELCOME__",
                                "source": "twilio"
                            }
                            await connection_manager.process_streaming_message(client_id, welcome_data)
                            
                        elif event == 'media':
                            # Handle Twilio media events with base64-encoded audio
                            media_data = data.get('media', {})
                            if media_data.get('track') == 'inbound' and 'payload' in media_data:
                                # Convert base64 payload to audio data
                                payload = media_data.get('payload')
                                audio_data = await stt_service.convert_twilio_audio(payload, client_id)
                                
                                if audio_data:
                                    # Process through STT service
                                    await stt_service.process_audio_chunk(client_id, audio_data, handle_transcription)
                                    audio_chunks += 1
                            
                        elif event == 'stop':
                            logger.info(f"[{connection_id}] STOP event received: {json.dumps(data)}")
                            # Process any remaining audio before closing
                            await stt_service.process_final_buffer(client_id, handle_transcription)
                            # Clean exit
                            websocket_closed = True
                            break
                        
                        elif event == 'mark':
                            logger.info(f"[{connection_id}] Mark event: {json.dumps(data)}")
                            
                        else:
                            logger.info(f"[{connection_id}] Unknown event type: {event}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"[{connection_id}] Non-JSON text received: {text_data[:50]}...")
                
                elif message.get('type') == 'websocket.disconnect':
                    logger.info(f"[{connection_id}] Received disconnect message")
                    await stt_service.process_final_buffer(client_id, handle_transcription)
                    websocket_closed = True
                    break
                
            except asyncio.TimeoutError:
                # Check for silence (no new transcriptions)
                current_time = time.time()
                is_silence = await stt_service.detect_silence(client_id, silence_threshold)
                
                if is_silence:
                    # Process any accumulated audio that hasn't been processed yet
                    await stt_service.process_final_buffer(client_id, handle_transcription)
                
                # Check if the WebSocket is still connected
                try:
                    if connected:
                        ping_data = json.dumps({"type": "ping"})
                        await websocket.send_text(ping_data)
                except Exception as e:
                    logger.warning(f"[{connection_id}] Connection appears closed: {str(e)}")
                    websocket_closed = True
                    break
                    
            except Exception as e:
                if "disconnect" in str(e).lower() or "closed" in str(e).lower():
                    logger.info(f"[{connection_id}] WebSocket disconnected: {str(e)}")
                    websocket_closed = True
                    break
                else:
                    logger.error(f"[{connection_id}] Error processing message: {str(e)}")
                    if "receive" in str(e) and "disconnect" in str(e):
                        websocket_closed = True
                        break
    
    except Exception as e:
        logger.error(f"[{connection_id}] Error in Twilio Media Stream handler: {str(e)}", exc_info=True)
    finally:
        # Clean up resources
        stt_service.close_session(client_id)
        
        if client_id and webrtc_manager.connection_manager:
            logger.info(f"[{connection_id}] Disconnecting client {client_id}")
            try:
                await webrtc_manager.connection_manager.cleanup_agent_resources(client_id)
                webrtc_manager.connection_manager.disconnect(client_id)
            except Exception as e:
                logger.error(f"[{connection_id}] Error during cleanup: {str(e)}")
        
        logger.info(f"[{connection_id}] Twilio Media Stream connection closed after {message_count} messages ({audio_chunks} audio chunks)")
    
        
@router.websocket("/signal/{peer_id}/{company_api_key}/{agent_id}")
async def signaling_endpoint(
    websocket: WebSocket,
    peer_id: str,
    company_api_key: str,
    agent_id: str,
    db: Session = Depends(get_db)
):
    """WebRTC signaling endpoint handler with Twilio Media Streams support"""
    connection_start = time.time()
    websocket_closed = False
    peer = None
    is_twilio_client = peer_id.startswith('twilio_')
    
    try:
        # Initialize the webrtc manager with the connection manager if not already set
        if not webrtc_manager.connection_manager and hasattr(websocket.app.state, 'connection_manager'):
            webrtc_manager.connection_manager = websocket.app.state.connection_manager
            logger.info("WebRTC manager linked to connection manager")
        
        # For Twilio clients, handle differently (no company validation required)
        if is_twilio_client:
            logger.info(f"Twilio client connected: {peer_id}")
            
            # Accept WebSocket connection immediately for Twilio
            try:
                await websocket.accept()
                logger.info(f"Twilio WebSocket connection accepted for {peer_id}")
            except Exception as e:
                logger.error(f"Error accepting Twilio connection: {str(e)}")
                websocket_closed = True
                return
            
            # For Twilio, we'll use a different handler that's optimized for Media Streams
            await handle_twilio_media_stream(websocket, peer_id, company_api_key, agent_id, db)
            return
            
        # Regular WebRTC clients continue with company validation
        company_validation_start = time.time()
        company = db.query(Company).filter_by(api_key=company_api_key).first()
        company_validation_time = time.time() - company_validation_start
        logger.info(f"Company validation took {company_validation_time:.3f}s")
        
        if not company:
            logger.warning(f"Invalid API key: {company_api_key}")
            try:
                await websocket.close(code=4001)
                websocket_closed = True
            except Exception as e:
                logger.error(f"Error closing websocket: {str(e)}")
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
        try:
            await websocket.accept()
            peer = await webrtc_manager.register_peer(peer_id, company_info, websocket)
            connect_time = time.time() - connect_start
            logger.info(f"WebRTC connection setup took {connect_time:.3f}s")
        except Exception as e:
            logger.error(f"Error accepting connection: {str(e)}")
            websocket_closed = True
            return
        
        # Send ICE servers configuration
        try:
            await peer.send_message({
                'type': 'config',
                'ice_servers': [
                    {'urls': ['stun:stun.l.google.com:19302']},
                    # Add TURN servers here for production
                ]
            })
        except Exception as e:
            logger.error(f"Error sending ICE config: {str(e)}")
            websocket_closed = True
            return
        
        # Main message loop
        while not websocket_closed:
            loop_start = time.time()
            message_type = None  # Initialize message_type at the start of each loop
            
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
                elif message_type == 'audio':
                    # Handle audio messages
                    result = await webrtc_manager.handle_audio_message(peer_id, data)
                    # Send result back to the peer
                    await peer.send_message({
                        "type": "audio_response",
                        "data": result
                    })
                elif message_type == 'message':
                    # Handle streaming messages directly using webrtc_manager
                    await webrtc_manager.process_streaming_message(peer_id, data)
                elif message_type == 'ping':
                    await peer.send_message({'type': 'pong'})
                    
                process_time = time.time() - process_start
                
                # Only log detailed timing for non-audio messages to reduce log volume
                if message_type and message_type != 'audio' or (message_type == 'audio' and data.get('action') != 'audio_chunk'):
                    logger.info(f"Message processing took {process_time:.3f}s for type {message_type}")
                
                # Only log complete cycle for non-audio-chunk messages to reduce log volume
                if message_type and message_type != 'audio' or (message_type == 'audio' and data.get('action') != 'audio_chunk'):
                    loop_time = time.time() - loop_start
                    logger.info(f"Complete message cycle took {loop_time:.3f}s")
                
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    ping_start = time.time()
                    await peer.send_message({"type": "ping"})
                    logger.debug(f"Heartbeat ping sent in {time.time() - ping_start:.3f}s")
                except Exception as e:
                    logger.error(f"Error sending heartbeat: {str(e)}")
                    websocket_closed = True
                    break
            except Exception as e:
                logger.error(f"Error in message processing: {str(e)}")
                websocket_closed = True
                break
            
    except Exception as e:
        logger.error(f"Error in signaling endpoint: {str(e)}")
    finally:
        # Clean up peer connection
        try:
            cleanup_start = time.time()
            await webrtc_manager.unregister_peer(peer_id)
            cleanup_time = time.time() - cleanup_start
            
            total_time = time.time() - connection_start
            logger.info(
                f"Connection ended for peer {peer_id}. "
                f"Duration: {total_time:.3f}s, "
                f"Cleanup time: {cleanup_time:.3f}s"
            )
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")



@router.get("/audio/streams/{company_api_key}")
async def get_audio_streams(
    company_api_key: str,
    db: Session = Depends(get_db)
):
    """Get information about active audio streams for a company"""
    company = db.query(Company).filter_by(api_key=company_api_key).first()
    if not company:
        raise HTTPException(status_code=401, detail="Invalid API key")
        
    company_id = str(company.id)
    active_peers = webrtc_manager.get_company_peers(company_id)
    
    # Collect audio stream info for each peer
    stream_info = {}
    for peer_id in active_peers:
        peer_audio_info = webrtc_manager.audio_handler.get_active_stream_info(peer_id)
        if peer_audio_info.get("is_active", False):
            stream_info[peer_id] = peer_audio_info.get("stream_info", {})
    
    return {
        "company_id": company_id,
        "active_audio_streams": len(stream_info),
        "streams": stream_info
    }

@router.get("/audio/stats")
async def get_audio_stats():
    """Get audio processing statistics"""
    return webrtc_manager.audio_handler.get_stats()

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
    except Exception as e:
        logger.error(f"Error in health check: {str(e)}")
    finally:
        try:
            await websocket.close()
        except Exception as e:
            logger.error(f"Error closing health check websocket: {str(e)}")