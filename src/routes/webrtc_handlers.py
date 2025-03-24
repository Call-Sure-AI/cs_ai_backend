# src/routes/webrtc_handlers.py
from fastapi import APIRouter, WebSocket, Depends, HTTPException, Request, FastAPI
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
from services.speech.tts_service import WebSocketTTSService
from services.speech.deepgram_ws_service import DeepgramWebSocketService


# Initialize router and logging
router = APIRouter()
setup_logging()
logger = logging.getLogger(__name__)

# Initialize services
vector_store = QdrantService()
webrtc_manager = WebRTCManager()

stt_service = SpeechToTextService() 


import asyncio
import subprocess
import base64
import json
import time
import uuid
from fastapi import FastAPI
from datetime import datetime
import logging
import os
import tempfile




async def process_buffered_message(manager, client_id, msg_data, app):
    """Process messages with improved latency"""
    try:
        # Get WebSocket connection
        ws = manager.active_connections.get(client_id)
        if not ws or manager.websocket_is_closed(ws):
            logger.warning(f"Client {client_id} disconnected before processing")
            return

        # Get agent and resources
        agent_res = manager.agent_resources.get(client_id)
        if not agent_res:
            logger.error(f"No agent resources for client {client_id}")
            return

        chain = agent_res.get('chain')
        rag_service = agent_res.get('rag_service')
        if not chain or not rag_service:
            logger.error(f"Missing resources in agent for client {client_id}")
            return

        # Get the stream SID for sending audio
        stream_sid = app.state.stream_sids.get(client_id, "")
        if not stream_sid:
            logger.error(f"No stream SID found for client {client_id}")
            return
        
        # Function to send audio to Twilio
        async def send_audio_to_twilio(audio_bytes):
            try:
                if not hasattr(send_audio_to_twilio, "chunk_count"):
                    send_audio_to_twilio.chunk_count = 0
                
                send_audio_to_twilio.chunk_count += 1
                
                if send_audio_to_twilio.chunk_count == 1:
                    logger.info(f"Received first audio chunk of {len(audio_bytes)} bytes from ElevenLabs")
                
                encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": encoded_audio}
                }
                await ws.send_text(json.dumps(media_message))
                
                if send_audio_to_twilio.chunk_count == 1:
                    logger.info(f"Sent first audio chunk to Twilio: {len(encoded_audio)} bytes encoded payload")
                return True
            except Exception as e:
                logger.error(f"Error sending audio to Twilio: {str(e)}")
                return False
        
        # Special handling for preset responses to minimize latency
        if msg_data.get('message') == '__SYSTEM_WELCOME__':
            # Hardcoded welcome message for immediate response
            welcome_text = "Hello! Welcome to Callsure AI. I'm your AI voice assistant. How may I help you today?"
            
            # Connect to TTS service
            tts_service = WebSocketTTSService()
            connect_start = time.time()
            connect_success = await tts_service.connect(send_audio_to_twilio)
            connect_time = time.time() - connect_start
            logger.info(f"TTS connection established in {connect_time:.2f}s")
            
            if connect_success:
                await tts_service.stream_text(welcome_text)
                # Give audio generation time to complete
                await asyncio.sleep(1.5)
                await tts_service.close()
            
            logger.info("Completed response: " + welcome_text)
            return welcome_text
            
        # For simple greetings, use fast-path response
        input_text = msg_data.get('message', '').lower().strip()
        if input_text in ['hello', 'hello?', 'hi', 'hey']:
            fast_response = "Hello! How can I assist you today?"
            
            # Use TTS service for quick response
            tts_service = WebSocketTTSService()
            await tts_service.connect(send_audio_to_twilio)
            await tts_service.stream_text(fast_response)
            # Wait for audio to process
            await asyncio.sleep(1.5)
            await tts_service.close()
            
            logger.info("Completed response: " + fast_response)
            return fast_response
        
        # Start TTS connection early to minimize latency
        tts_service = WebSocketTTSService()
        tts_connect_task = asyncio.create_task(tts_service.connect(send_audio_to_twilio))
        
        # Collect the full response for logging
        full_response_text = ""
        current_sentence = ""
        
        # Start processing LLM response
        logger.info(f"Getting answer for input: '{msg_data.get('message', '')}'")
        
        # Ensure TTS connection is ready before we need it
        connect_success = await tts_connect_task
        
        # Stream response with sentence-by-sentence TTS
        async for token in rag_service.get_answer_with_chain(
            chain=chain,
            question=msg_data.get('message', ''),
            company_name="Callsure AI"
        ):
            # Add token to text
            full_response_text += token
            current_sentence += token
            
            # Stream text to client UI if connected
            if not manager.websocket_is_closed(ws):
                try:
                    await manager.send_json(ws, {"type": "stream_chunk", "text_content": token})
                except Exception as e:
                    logger.error(f"Error sending stream chunk: {str(e)}")
            
            # Process sentence as soon as it's complete for faster audio
            ends_sentence = any(p in token for p in ".!?")
            
            # Also process on commas after a minimum length to start audio sooner
            process_on_comma = "," in token and len(current_sentence) > 40
            
            if (ends_sentence or process_on_comma) and current_sentence.strip() and connect_success:
                # Process immediately to reduce latency
                asyncio.create_task(tts_service.stream_text(current_sentence))
                current_sentence = "" if ends_sentence else ""
            
            # Small delay to avoid CPU overload
            await asyncio.sleep(0.01)

        # Send any remaining text
        if current_sentence.strip() and connect_success:
            await tts_service.stream_text(current_sentence)
        
        # Wait for audio to finish
        await asyncio.sleep(0.8)
        
        # Close TTS connection
        if connect_success:
            await tts_service.stream_end()
            await asyncio.sleep(0.2)
            await tts_service.close()
        
        logger.info(f"Completed response: {full_response_text}")
        return full_response_text

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        if 'tts_service' in locals() and tts_service is not None:
            await tts_service.close()
        return None

async def process_message_with_retries(manager, cid, msg_data, app, max_retries=3):
    retries = 0
    success = False
    while retries < max_retries and not success:
        try:
            await process_buffered_message(manager, cid, msg_data, app)
            success = True
        except Exception as e:
            retries += 1
            logger.error(f"[{cid}] Error processing message (retry {retries}): {str(e)}")
            await asyncio.sleep(0.5)
    return



async def handle_twilio_media_stream_with_deepgram(websocket: WebSocket, peer_id: str, company_api_key: str, agent_id: str, db: Session):
    """Handler for Twilio Media Streams using Deepgram WebSocket for transcription."""
    app = websocket.app  # Get FastAPI app instance
    connection_manager = app.state.connection_manager
    client_id = peer_id
    connection_id = str(uuid.uuid4())[:8]
    message_count = 0
    audio_chunks = 0
    connected = False
    websocket_closed = False
    
    # Create Deepgram speech service using WebSocket
    speech_service = DeepgramWebSocketService()
    
    # Track when we last heard the user speak to implement silence detection
    last_speech_time = time.time()
    is_processing = False
    silence_threshold = 2.0  # 2 seconds of silence to trigger processing
    welcome_sent = False
    
    try:
        logger.info(f"[{connection_id}] Handling Twilio call for {peer_id}")

        # Get connection manager
        connection_manager = webrtc_manager.connection_manager
        if not connection_manager:
            logger.error(f"[{connection_id}] Connection manager not found!")
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
            
        # Set company info
        company_info = {
            "id": company.id,
            "name": company.name or "Customer Support"
        }
        
        connection_manager.client_companies[client_id] = company_info
        
        # Connect client
        await connection_manager.connect(websocket, client_id)
        logger.info(f"[{connection_id}] Client {client_id} connected")
        connected = True
        
        # Initialize agent
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
        
        # Initialize agent resources
        success = await connection_manager.initialize_agent_resources(client_id, company_info["id"], agent)
        if not success:
            logger.error(f"[{connection_id}] Failed to initialize agent resources")
            await websocket.close(code=1011)
            websocket_closed = True
            return

        # Define the transcript callback function for Deepgram
        async def handle_transcription(session_id, transcribed_text):
            """Handle transcripts from Deepgram"""
            nonlocal is_processing, last_speech_time
            
            # Update last speech time for silence detection
            last_speech_time = time.time()
            
            # If empty text is returned, it might indicate end of utterance
            if not transcribed_text or not transcribed_text.strip():
                # No need to process empty transcripts
                return
                
            logger.info(f"[{connection_id}] TRANSCRIBED: '{transcribed_text}'")
            
            is_processing = True
            
            message_data = {
                "type": "message",
                "message": transcribed_text,
                "source": "twilio"
            }
            
            # Process the speech
            try:
                await process_buffered_message(connection_manager, client_id, message_data, app)
            except Exception as e:
                logger.error(f"[{connection_id}] Error processing message: {str(e)}")
            finally:
                is_processing = False
        
        # Initialize Deepgram WebSocket session
        logger.info(f"[{connection_id}] Initializing Deepgram WebSocket session")
        init_success = await speech_service.initialize_session(client_id, handle_transcription)
        if not init_success:
            logger.error(f"[{connection_id}] Failed to initialize Deepgram WebSocket session")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        logger.info(f"[{connection_id}] Deepgram WebSocket session initialized successfully")
        
        # Main processing loop
        while not websocket_closed:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                message_count += 1

                if message.get('type') == 'websocket.disconnect':
                    logger.info(f"[{connection_id}] Received disconnect message")
                    websocket_closed = True
                    break

                if 'bytes' in message:
                    # Raw audio data received - forward directly to WebSocket
                    logger.info(f"[{connection_id}] Received audio chunk with size {len(message['bytes'])}")
                    audio_data = message['bytes']
                    audio_chunks += 1
                    await speech_service.process_audio_chunk(client_id, audio_data)
                    last_speech_time = time.time()
                     
                elif 'text' in message:
                    # Text JSON message received
                    logger.info(f"[{connection_id}] Received text message size : {len(message['text'])}")
                    text_data = message['text']
                    try:
                        data = json.loads(text_data)
                        event = data.get('event')
                        
                        if event in ['connected', 'start', 'stop']:
                            logger.info(f"[{connection_id}] Twilio event: {event}")
                        
                        if event == 'start':
                            stream_sid = data.get('streamSid')
                            if not stream_sid:
                                logger.error(f"[{connection_id}] Missing streamSid in start event")
                                return

                            # Save the stream SID for later use in sending audio
                            if not hasattr(app.state, 'stream_sids'):
                                app.state.stream_sids = {}
                            app.state.stream_sids[client_id] = stream_sid

                            call_sid = data.get('start', {}).get('callSid')
                            if call_sid:
                                if not hasattr(app.state, 'client_call_mapping'):
                                    app.state.client_call_mapping = {}
                                app.state.client_call_mapping[client_id] = call_sid

                            logger.info(f"[{connection_id}] Call started: streamSid={stream_sid}, callSid={call_sid}")

                            if not connected:
                                await websocket.send_text(json.dumps({
                                    "event": "connected",
                                    "protocol": "websocket",
                                    "version": "1.0.0"
                                }))
                                connected = True

                            # Send welcome message
                            if not welcome_sent:
                                welcome_data = {"type": "message", "message": "__SYSTEM_WELCOME__", "source": "twilio"}
                                asyncio.create_task(process_buffered_message(connection_manager, client_id, welcome_data, app))
                                welcome_sent = True
                        
                        elif event == 'media':
                            try:
                                # Your existing code
                                media_data = data.get('media', {})
                                if media_data.get('track') == 'inbound' and 'payload' in media_data:
                                    payload = media_data.get('payload')
                                    
                                    # Convert Twilio audio format for processing
                                    audio_data = await speech_service.convert_twilio_audio(payload, client_id)
                                    if audio_data:
                                        logger.info(f"[{connection_id}] Converted audio: {len(audio_data)} bytes")
                                        
                                        try:
                                            # Process the audio through Deepgram WebSocket
                                            success = await speech_service.process_audio_chunk(client_id, audio_data)
                                            if success:
                                                logger.info(f"[{connection_id}] Successfully processed audio chunk")
                                                audio_chunks += 1
                                                last_speech_time = time.time()
                                            else:
                                                logger.warning(f"[{connection_id}] Failed to process audio chunk")
                                        except Exception as e:
                                            # Don't let this error crash the entire connection
                                            logger.error(f"[{connection_id}] Error processing audio chunk: {str(e)}")
                                            
                            except Exception as e:
                                # This is for more serious errors that should close the connection
                                logger.error(f"[{connection_id}] Error in message loop: {str(e)}")
                                websocket_closed = True
                                break
                            
                            
                        elif event == 'stop':
                            logger.info(f"[{connection_id}] Call ended")
                            websocket_closed = True
                            break
                        
                    except json.JSONDecodeError:
                        logger.warning(f"[{connection_id}] Invalid JSON received")
                
                # Check for connection health
                if connection_manager.websocket_is_closed(websocket):
                    logger.warning(f"[{connection_id}] WebSocket detected as closed")
                    websocket_closed = True
                    break

            except asyncio.TimeoutError:
                # Just a timeout in the receive loop, continue
                pass
            
            except Exception as e:
                logger.error(f"[{connection_id}] Error in message loop: {str(e)}")
                websocket_closed = True
                break

    except Exception as e:
        logger.error(f"[{connection_id}] Error in Twilio handler: {str(e)}")
    
    finally:
        # Clean up
        await speech_service.close_session(client_id)
        
        if client_id and connection_manager:
            logger.info(f"[{connection_id}] Disconnecting client {client_id}")
            try:
                await connection_manager.cleanup_agent_resources(client_id)
                connection_manager.disconnect(client_id)
            except Exception as e:
                logger.error(f"[{connection_id}] Error during cleanup: {str(e)}")
                
        logger.info(f"[{connection_id}] Call ended after {message_count} messages ({audio_chunks} audio chunks)")
        
        
                          
        
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
            
            # For Twilio, we'll use the Deepgram-based handler
            await handle_twilio_media_stream_with_deepgram(websocket, peer_id, company_api_key, agent_id, db)
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
            
            
            await websocket.send_json({
                "type": "connection_ack",
                "status": "success",
                "peer_id": peer_id
            })
            logger.info(f"Connection acknowledgment sent to {peer_id}")
            peer = await webrtc_manager.register_peer(peer_id, company_info, websocket)
            connect_time = time.time() - connect_start
            logger.info(f"WebRTC connection setup took {connect_time:.3f}s")
        except Exception as e:
            logger.error(f"Error accepting connection: {str(e)}")
            websocket_closed = True
            return
        
        # Send ICE servers configuration
        try:
            logger.info(f"Attempting to send ICE config to {peer_id}")
            config_message = {
                'type': 'config',
                'ice_servers': [
                    {'urls': ['stun:stun.l.google.com:19302']},
                    # Add TURN servers here for production
                ]
            }
            await websocket.send_json(config_message)
            logger.info(f"ICE config sent successfully to {peer_id}")
        except Exception as e:
            logger.error(f"Error sending ICE config: {str(e)}", exc_info=True)
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
                logger.info(f"Received message of type: {message_type} and data: {data}")
                
                # Add this after the signal processing code in the main loop
                if message_type == 'signal':
                    # After attempting to relay the signal
                    to_peer = data.get('to_peer')
                    
                    # If the relay failed and it was a signal to the server
                    if to_peer == 'server' and data.get('data', {}).get('type') == 'offer':
                        try:
                            # Send a direct answer to keep the connection alive
                            logger.info(f"Sending direct answer to {peer_id}")
                            await peer.send_message({
                                'type': 'signal',
                                'from_peer': 'server',
                                'data': {
                                    'type': 'answer',
                                    'sdp': {
                                        'type': 'answer',
                                        'sdp': 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=msid-semantic: WMS\r\n'
                                    }
                                }
                            })
                        except Exception as e:
                            logger.error(f"Error sending direct answer: {str(e)}")
                            
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
                    await webrtc_manager.process_streaming_message(peer_id, data, agent_id)
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