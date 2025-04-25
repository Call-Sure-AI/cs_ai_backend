# src/routes/webrtc_handlers.py
from fastapi import APIRouter, WebSocket, Depends, HTTPException, Request, FastAPI
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging
import json
from datetime import datetime
import asyncio
import time
import random

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

# Audio buffer for each client
audio_buffers = {}
# Last speech timestamp for silence detection
last_speech_timestamps = {}
# Processing flags to avoid duplicate processing
is_processing = {}
# Silence threshold in seconds
SILENCE_THRESHOLD = 2.0


async def handle_audio_stream(peer_id: str, audio_data: bytes, manager: WebRTCManager, app: FastAPI):
    """Handle incoming audio stream, transcribe and process when silence is detected"""
    # Initialize speech service if needed
    if peer_id not in manager.speech_services:
        speech_service = DeepgramWebSocketService()
        
        # Define callback for transcription results
        async def transcription_callback(session_id, transcribed_text):
            # Store the transcript in the app state
            if hasattr(app.state, 'transcripts') and peer_id in app.state.transcripts:
                app.state.transcripts[peer_id] = transcribed_text
            else:
                if not hasattr(app.state, 'transcripts'):
                    app.state.transcripts = {}
                app.state.transcripts[peer_id] = transcribed_text
        
        # Initialize Deepgram session
        success = await speech_service.initialize_session(peer_id, transcription_callback)
        if success:
            manager.speech_services[peer_id] = speech_service
    
    # Process the audio chunk with Deepgram
    speech_service = manager.speech_services.get(peer_id)
    if speech_service:
        await speech_service.process_audio_chunk(peer_id, audio_data)
    
    # Start silence detection task if not already running
    if not hasattr(app.state, 'silence_detection_tasks') or peer_id not in app.state.silence_detection_tasks:
        if not hasattr(app.state, 'silence_detection_tasks'):
            app.state.silence_detection_tasks = {}
        task = asyncio.create_task(silence_detection_loop(peer_id, manager, app))
        app.state.silence_detection_tasks[peer_id] = task
        
# # In silence_detection_loop
# async def silence_detection_loop(peer_id: str, manager: WebRTCManager, app: FastAPI):
#     """Loop to detect silence and trigger processing when user stops speaking"""
#     logger.info(f"Starting silence detection loop for {peer_id}")
#     try:
#         loop_count = 0
        
#         while True:
#             # Check if we should stop the loop
#             if peer_id not in last_speech_timestamps:
#                 logger.info(f"Stopping silence detection for {peer_id} - client disconnected")
#                 break
                
#             # Get last speech timestamp
#             last_speech = last_speech_timestamps.get(peer_id, 0)
#             current_time = time.time()
#             silence_duration = current_time - last_speech
            
#             # Log status periodically
#             if loop_count % 50 == 0:
#                 pass # Log every ~5 seconds (assuming 0.1s sleep)
#                 # logger.debug(f"Silence duration for {peer_id}: {silence_duration:.2f}s, threshold: {SILENCE_THRESHOLD}s")
#             loop_count += 1
            
#             # If silence threshold exceeded and not already processing
#             if silence_duration >= SILENCE_THRESHOLD and not is_processing.get(peer_id, False):
#                 # logger.info(f"Silence threshold exceeded for {peer_id}: {silence_duration:.2f}s")
                
#                 # Check transcripts to see if we have anything
#                 if hasattr(app.state, 'transcripts'):
#                     if peer_id in app.state.transcripts:
#                         transcript = app.state.transcripts.get(peer_id)
#                         logger.info(f"Found transcript for {peer_id}: '{transcript}'")
#                     else:
#                         logger.info(f"No transcript found for {peer_id} in app.state.transcripts")
#                 else:
#                     logger.info(f"app.state does not have 'transcripts' attribute")
                
#                 # Check if we have a transcript to process
#                 if hasattr(app.state, 'transcripts') and peer_id in app.state.transcripts:
#                     transcript = app.state.transcripts.get(peer_id)
                    
#                     if transcript and transcript.strip():
#                         logger.info(f"Processing transcript after silence for {peer_id}: '{transcript}'")
                        
#                         # Mark as processing to avoid duplicate processing
#                         is_processing[peer_id] = True
                        
#                         # Process the transcript and get response
#                         message_data = {
#                             "type": "message",
#                             "message": transcript,
#                             "source": "audio"
#                         }
                        
#                         # Clear the transcript to avoid reprocessing
#                         app.state.transcripts[peer_id] = ""
                        
#                         # Process the message and get response with audio
#                         try:
#                             # Use the existing function for processing with TTS
#                             await process_message_with_audio_response(manager, peer_id, message_data, app)
#                         except Exception as e:
#                             logger.error(f"Error processing transcript: {str(e)}")
#                         finally:
#                             # Reset processing flag
#                             is_processing[peer_id] = False
#                     else:
#                         logger.debug(f"No valid transcript to process for {peer_id}")
#                 else:
#                     logger.debug(f"No transcript available for {peer_id}")
            
#             # Sleep before next check (100ms)
#             await asyncio.sleep(0.1)
            
#     except asyncio.CancelledError:
#         logger.info(f"Silence detection task cancelled for {peer_id}")
#     except Exception as e:
#         logger.error(f"Error in silence detection loop for {peer_id}: {str(e)}")
#     finally:
#         # Clean up
#         if hasattr(app.state, 'silence_detection_tasks') and peer_id in app.state.silence_detection_tasks:
#             app.state.silence_detection_tasks.pop(peer_id, None)
#             logger.info(f"Removed silence detection task for {peer_id}")

# Then modify the silence_detection_loop function to be more robust
async def silence_detection_loop(peer_id: str, manager: WebRTCManager, app: FastAPI):
    """Loop to detect silence and trigger processing when user stops speaking"""
    logger.info(f"Starting silence detection loop for {peer_id}")
    try:
        loop_count = 0
        # Track if we're currently processing a response
        processing_response = False
        last_transcript = ""
        
        while True:
            # Check if we should stop the loop
            if peer_id not in last_speech_timestamps:
                logger.info(f"Stopping silence detection for {peer_id} - client disconnected")
                break
                
            # Get last speech timestamp
            last_speech = last_speech_timestamps.get(peer_id, 0)
            current_time = time.time()
            silence_duration = current_time - last_speech
            
            # Check transcripts to see if we have anything
            current_transcript = ""
            if hasattr(app.state, 'transcripts') and peer_id in app.state.transcripts:
                current_transcript = app.state.transcripts.get(peer_id, "")
            
            # If transcript changed while we're processing, we should interrupt and restart
            if processing_response and current_transcript and current_transcript != last_transcript:
                logger.info(f"New speech detected while processing for {peer_id}. Transcript: '{current_transcript}'")
                # We could implement cancellation of the current response here
                # For now, just update our state
                processing_response = False
                last_transcript = current_transcript
                last_speech = current_time  # Reset the silence timer
                last_speech_timestamps[peer_id] = current_time
            
            # If silence threshold exceeded and not already processing
            if silence_duration >= SILENCE_THRESHOLD and not processing_response and current_transcript.strip():
                logger.info(f"Silence threshold exceeded for {peer_id}: {silence_duration:.2f}s")
                logger.info(f"Processing transcript after silence for {peer_id}: '{current_transcript}'")
                
                # Mark as processing to avoid duplicate processing
                processing_response = True
                last_transcript = current_transcript
                
                # Process the transcript and get response
                message_data = {
                    "type": "message",
                    "message": current_transcript,
                    "source": "audio"
                }
                
                # Clear the transcript to avoid reprocessing
                app.state.transcripts[peer_id] = ""
                
                # Process the message and get response with audio
                try:
                    # Use the existing function for processing with TTS
                    await process_message_with_audio_response(manager, peer_id, message_data, app)
                except Exception as e:
                    logger.error(f"Error processing transcript: {str(e)}")
                finally:
                    # Reset processing flag
                    processing_response = False
            
            # Sleep before next check (100ms)
            await asyncio.sleep(0.1)
            
    except asyncio.CancelledError:
        logger.info(f"Silence detection task cancelled for {peer_id}")
    except Exception as e:
        logger.error(f"Error in silence detection loop for {peer_id}: {str(e)}")
    finally:
        # Clean up
        if hasattr(app.state, 'silence_detection_tasks') and peer_id in app.state.silence_detection_tasks:
            app.state.silence_detection_tasks.pop(peer_id, None)
            logger.info(f"Removed silence detection task for {peer_id}")


# Modify your WebRTCManager class to include speech services
async def initialize_webrtc_manager(manager):
    """Initialize the WebRTC manager with needed components for audio processing"""
    if not hasattr(manager, 'speech_services'):
        manager.speech_services = {}

async def handle_audio_message(manager, peer_id, message_data, app):
    """Enhanced audio message handler that adds transcription"""
    if peer_id not in manager.peers:
        logger.warning(f"Audio message received for unknown peer: {peer_id}")
        return {"status": "error", "error": "Unknown peer"}
    
    action = message_data.get("action", "")
    
    if action == "start_stream":
        # Initialize speech service on stream start
        if peer_id not in manager.speech_services:
            logger.info(f"Creating Deepgram service for {peer_id}")
            speech_service = DeepgramWebSocketService()
            
            # Define callback for transcription results - MODIFIED TO PROCESS IMMEDIATELY
            # async def transcription_callback(session_id, transcribed_text):
            #     if not transcribed_text:
            #         logger.debug(f"Empty transcription for {session_id}")
            #         return
                    
            #     logger.info(f"Transcription for {peer_id}: '{transcribed_text}'")
                
            #     # Update timestamp for activity tracking
            #     last_speech_timestamps[peer_id] = time.time()
                
            #     # Store the transcript in the app state
            #     if not hasattr(app.state, 'transcripts'):
            #         app.state.transcripts = {}
            #     app.state.transcripts[peer_id] = transcribed_text
            #     logger.info(f"Stored transcript for {peer_id}: '{transcribed_text}'")
                
            #     # IMPORTANT: Process the transcript immediately when received
            #     # This ensures we don't need to wait for silence detection
            #     message_data = {
            #         "type": "message",
            #         "message": transcribed_text,
            #         "source": "audio"
            #     }
                
            #     # Process in a separate task to avoid blocking
            #     asyncio.create_task(process_message_with_audio_response(
            #         manager, peer_id, message_data, app
            #     ))
            
            async def transcription_callback(session_id, transcribed_text):
                if not transcribed_text:
                    logger.debug(f"Empty transcription for {session_id}")
                    return
                    
                logger.info(f"Transcription for {peer_id}: '{transcribed_text}'")
                
                # Update timestamp for activity tracking
                last_speech_timestamps[peer_id] = time.time()
                
                # Store the transcript in the app state
                if not hasattr(app.state, 'transcripts'):
                    app.state.transcripts = {}
                app.state.transcripts[peer_id] = transcribed_text
                logger.info(f"Stored transcript for {peer_id}: '{transcribed_text}'")
                
            
            
            # Initialize Deepgram session with error handling
            try:
                success = await speech_service.initialize_session(peer_id, transcription_callback)
                if success:
                    manager.speech_services[peer_id] = speech_service
                    logger.info(f"Successfully initialized speech service for {peer_id}")
                    
                    # Still start silence detection as a backup mechanism
                    if not hasattr(app.state, 'silence_detection_tasks'):
                        app.state.silence_detection_tasks = {}
                    
                    task = asyncio.create_task(silence_detection_loop(peer_id, manager, app))
                    app.state.silence_detection_tasks[peer_id] = task
                    logger.info(f"Started silence detection for {peer_id}")
                else:
                    logger.error(f"Failed to initialize speech service for {peer_id}")
            except Exception as e:
                logger.error(f"Error initializing speech service: {str(e)}")
        
        # Start the audio stream in the audio handler
        result = await manager.audio_handler.start_audio_stream(
            peer_id, message_data.get("metadata", {})
        )
        logger.info(f"Started audio stream for peer {peer_id}: {result}")
        return result
        
    elif action == "audio_chunk":
        # Process audio chunk with audio handler
        result = await manager.audio_handler.process_audio_chunk(
            peer_id, message_data.get("chunk_data", {})
        )
        
        # Extract audio data (base64 encoded)
        audio_base64 = message_data.get("chunk_data", {}).get("audio_data", "")
        if audio_base64:
            try:
                # Decode base64 audio data
                audio_bytes = base64.b64decode(audio_base64)
                
                # Log audio chunk details (occasionally to avoid flooding logs)
                chunkCountRef = getattr(handle_audio_message, "chunkCount", 0) + 1
                handle_audio_message.chunkCount = chunkCountRef
                if chunkCountRef % 20 == 0:
                    audio_sample = ', '.join([str(b) for b in audio_bytes[:20]])
                    logger.info(f"Audio chunk #{chunkCountRef} for {peer_id}: {len(audio_bytes)} bytes, sample: [{audio_sample}]")
            
                # Get or initialize speech service
                speech_service = manager.speech_services.get(peer_id)
                if speech_service:
                    # Process for speech recognition
                    success = await speech_service.process_audio_chunk(peer_id, audio_bytes)
                    if not success:
                        logger.warning(f"Failed to process audio chunk for {peer_id}")
                    
                    # Update last speech timestamp
                    last_speech_timestamps[peer_id] = time.time()
                else:
                    logger.warning(f"No speech service available for {peer_id} - reinitializing")
                    # Re-attempt initialization (this is failsafe code)
                    if "start_stream" not in message_data:
                        # Create fake start_stream message to initialize
                        temp_msg = {
                            "action": "start_stream",
                            "metadata": {"auto_recovery": True}
                        }
                        await handle_audio_message(manager, peer_id, temp_msg, app)
            except Exception as e:
                logger.error(f"Error processing audio for speech recognition: {str(e)}")
        
        return result
        
    elif action == "end_stream":
        # End an audio stream
        result = await manager.audio_handler.end_audio_stream(
            peer_id, message_data.get("metadata", {})
        )
        logger.info(f"Ended audio stream for peer {peer_id}: {result}")
        
        # Force processing of any pending audio
        if peer_id in last_speech_timestamps:
            logger.info(f"Forcing processing for peer {peer_id} at stream end")
            last_speech_timestamps[peer_id] = time.time() - SILENCE_THRESHOLD - 1
            
            # Check if we have any transcript to process
            if hasattr(app.state, 'transcripts') and peer_id in app.state.transcripts:
                transcript = app.state.transcripts.get(peer_id)
                if transcript and transcript.strip():
                    logger.info(f"Processing final transcript for {peer_id}: '{transcript}'")
                    message_data = {
                        "type": "message",
                        "message": transcript,
                        "source": "audio"
                    }
                    # Process immediately without waiting for silence detection
                    asyncio.create_task(process_message_with_audio_response(
                        manager, peer_id, message_data, app
                    ))
                    
                    # Clear the transcript to avoid reprocessing
                    app.state.transcripts[peer_id] = ""
        
        return result
        
    else:
        logger.warning(f"Unknown audio action: {action}")
        return {"status": "error", "error": f"Unknown action: {action}"}


async def process_message_with_audio_response(manager, peer_id: str, message_data: dict, app):
    """Process a message and respond with streaming text and audio"""
    if peer_id not in manager.peers:
        logger.warning(f"Client {peer_id} not found")
        return
            
    peer = manager.peers[peer_id]
    msg_id = str(time.time())  # Unique message ID
    
    try:
        # Ensure agent resources are initialized
        if not manager.connection_manager:
            logger.error("Connection manager not initialized")
            return
                
        company_id = peer.company_id
        
        # Get agent resources
        agent_res = manager.connection_manager.agent_resources.get(peer_id)
        if not agent_res:
            logger.error(f"No agent resources found for {peer_id}")
            return
                
        chain = agent_res.get('chain')
        rag_service = agent_res.get('rag_service')
        
        if not chain or not rag_service:
            logger.error(f"Missing chain or rag service for {peer_id}")
            return
        
        # Initialize TTS service
        tts_service = WebSocketTTSService()
        
        # Define callback for sending audio back to the client
        async def send_audio_to_client(audio_base64):
            try:
                await peer.send_message({
                    "type": "stream_chunk",
                    "text_content": "",
                    "audio_content": audio_base64,
                    "msg_id": msg_id
                })
                return True
            except Exception as e:
                logger.error(f"Error sending audio chunk: {str(e)}")
                return False
        
        # Start TTS connection
        connect_success = await tts_service.connect(send_audio_to_client)
        if not connect_success:
            logger.error("Failed to connect to TTS service")
            return
        
        # For accumulating text
        current_sentence = ""
        full_response = ""
        
        # Get conversation context
        conversation_context = {}
        conversation = manager.connection_manager.client_conversations.get(peer_id)
        if conversation:
            conversation_context = await manager.agent_manager.get_conversation_context(conversation['id'])
        
        # Stream response tokens
        async for token in rag_service.get_answer_with_chain(
            chain=chain,
            question=message_data.get('message', ''),
            conversation_context=conversation_context
        ):
            # Log received token
            logger.info(f"Received token: '{token}'")
            
            # Add token to buffers
            full_response += token
            current_sentence += token
            
            # Send text token to client immediately
            await peer.send_message({
                "type": "stream_chunk",
                "text_content": token,
                "audio_content": None,
                "msg_id": msg_id
            })
            
            # Check for sentence end or significant pause
            if ('.' in token or '!' in token or '?' in token):
                
                # Only send if we have accumulated something meaningful
                if current_sentence.strip():
                    logger.info(f"Sending for TTS: '{current_sentence}'")
                    await tts_service.stream_text(current_sentence)
                    
                    # Reset only on sentence end, not on commas
                    if '.' in token or '!' in token or '?' in token:
                        current_sentence = ""
                    
                    # Give time for processing
                    await asyncio.sleep(0.3)
            
            # Small delay
            await asyncio.sleep(0.01)
        
        # Process any remaining text
        if current_sentence.strip():
            logger.info(f"Sending final text for TTS: '{current_sentence}'")
            await tts_service.stream_text(current_sentence)
            await asyncio.sleep(0.3)
        
        # Ensure all audio is processed
        await tts_service.flush()
        await asyncio.sleep(1.5)
        
        # Close TTS service properly
        await tts_service.stream_end()
        await asyncio.sleep(0.5)
        await tts_service.close()
        
        # Send end of stream message
        await peer.send_message({
            "type": "stream_end",
            "msg_id": msg_id
        })
        
        logger.info(f"Completed response for {peer_id}")
        return full_response
    
    except Exception as e:
        logger.error(f"Error processing message with audio: {str(e)}")
        if 'tts_service' in locals() and tts_service is not None:
            await tts_service.close()
        return None


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
        stream_sid = app.state.stream_sids.get(client_id)
        if not stream_sid:
            logger.error(f"No stream SID found for client {client_id}")
            return
        
        # Function to send audio to Twilio
        async def send_audio_to_twilio(audio_base64):
            try:
                if not hasattr(send_audio_to_twilio, "chunk_count"):
                    send_audio_to_twilio.chunk_count = 0
                
                send_audio_to_twilio.chunk_count += 1
                
                if send_audio_to_twilio.chunk_count == 1:
                    logger.info(f"Received first audio chunk from ElevenLabs")
                
                # Simple, direct approach - exactly what Twilio expects
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": audio_base64
                    }
                }
                
                # Send as JSON text
                await ws.send_text(json.dumps(media_message))
                
                if send_audio_to_twilio.chunk_count == 1:
                    logger.info(f"Sent first audio chunk to Twilio")
                
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
            connect_success = await tts_service.connect(
                lambda audio_base64: send_audio_to_twilio(audio_base64, stream_sid, ws)
            )
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

        # Extract businessContext and roleDescription from additional_context if available
        additional_context = agent_record.additional_context or {}
        business_context = additional_context.get('businessContext', '')
        role_description = additional_context.get('roleDescription', '')

        # Create a prompt based on additional_context
        prompt = agent_record.prompt
        if business_context and role_description:
            # Combine the business context and role description into the prompt
            prompt = f"{business_context} {role_description}"
        elif business_context:
            prompt = business_context
        elif role_description:
            prompt = role_description

        # Use new prompt in the agent info
        agent = {
            "id": agent_record.id,
            "name": agent_record.name,
            "type": agent_record.type,
            "prompt": prompt,  # Use the updated prompt
            "confidence_threshold": agent_record.confidence_threshold,
            "additional_context": agent_record.additional_context  # Include this for completeness
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
                    # logger.info(f"[{connection_id}] Received text message size : {len(message['text'])}")
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
                                        # logger.info(f"[{connection_id}] Converted audio: {len(audio_data)} bytes")
                                        
                                        try:
                                            # Process the audio through Deepgram WebSocket
                                            success = await speech_service.process_audio_chunk(client_id, audio_data)
                                            if success:
                                                # logger.info(f"[{connection_id}] Successfully processed audio chunk")
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
        
        
        
from managers.agent_manager import AgentManager

async def initialize_client_resources(websocket: WebSocket, peer_id: str, company_id: str, agent_id: str, db: Session):
    """Initialize agent resources for the client"""
    try:
        # Get the connection manager from the app state
        connection_manager = websocket.app.state.connection_manager
        
        if not agent_id:
            logger.error(f"No agent_id provided for {peer_id}")
            return False
        
        # Prepare agent info - Just pass the ID, don't fetch base agent
        agent_info = {
            'id': agent_id,
            'company_id': company_id
        }
        
        # Initialize agent resources
        success = await connection_manager.initialize_agent_resources(
            peer_id, 
            company_id, 
            agent_info
        )
        
        if not success:
            logger.error(f"Failed to initialize agent resources for {peer_id}")
            return False
        
        # Set the active agent
        connection_manager.active_agents[peer_id] = agent_id
        
        logger.info(f"Successfully initialized agent resources for {peer_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error initializing client resources: {str(e)}")
        return False
    

@router.websocket("/signal/{peer_id}/{company_api_key}/{agent_id}")
async def signaling_endpoint(
    websocket: WebSocket,
    peer_id: str,
    company_api_key: str,
    agent_id: str,
    db: Session = Depends(get_db)
):
    """WebRTC signaling endpoint handler with audio integration"""
    connection_start = time.time()
    websocket_closed = False
    peer = None
    is_twilio_client = peer_id.startswith('twilio_')
    
    try:
        # Initialize the webrtc manager with the connection manager if not already set
        if not webrtc_manager.connection_manager and hasattr(websocket.app.state, 'connection_manager'):
            webrtc_manager.connection_manager = websocket.app.state.connection_manager
            logger.info("WebRTC manager linked to connection manager")
        
        # Initialize audio-related components
        await initialize_webrtc_manager(webrtc_manager)
        
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
        
        # CRITICAL: Initialize client resources IMMEDIATELY after connection
        resource_init_start = time.time()
        resources_initialized = await initialize_client_resources(
            websocket, 
            peer_id, 
            str(company.id), 
            agent_id, 
            db
        )
        resource_init_time = time.time() - resource_init_start
        logger.info(f"Agent resources initialization took {resource_init_time:.3f}s")
        
        if not resources_initialized:
            logger.error(f"Failed to initialize agent resources for {peer_id}")
            try:
                await websocket.close(code=4002)
                websocket_closed = True
            except Exception as e:
                logger.error(f"Error closing websocket after resource init failure: {str(e)}")
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
                    timeout=30.0  # Increased timeout for audio processing
                )
                receive_time = time.time() - receive_start
                
                # Process received message
                process_start = time.time()
                message_type = data.get('type')
                
                if message_type != 'audio' or data.get('action') != 'audio_chunk':
                    logger.info(f"Received message of type: {message_type}")
                
                if message_type == 'signal':
                    # Handle signaling messages
                    to_peer = data.get('to_peer')
                    result = await webrtc_manager.relay_signal(peer_id, to_peer, data.get('data', {}))
                    
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
                    # Handle audio messages with enhanced handler
                    result = await handle_audio_message(webrtc_manager, peer_id, data, websocket.app)
                    
                    # Send result back to the peer
                    await peer.send_message({
                        "type": "audio_response",
                        "data": result
                    })
                    
                elif message_type == 'message':
                    # Handle text messages with audio response
                    await process_message_with_audio_response(webrtc_manager, peer_id, data, websocket.app)
                    
                elif message_type == 'ping':
                    await peer.send_message({'type': 'pong'})
                    
                process_time = time.time() - process_start
                
                # Only log detailed timing for non-audio messages to reduce log volume
                if message_type and message_type != 'audio' or (message_type == 'audio' and data.get('action') != 'audio_chunk'):
                    logger.info(f"Message processing took {process_time:.3f}s for type {message_type}")
                
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
        # Clean up peer connection and audio resources
        try:
            cleanup_start = time.time()
            
            # Clean up speech services
            if hasattr(webrtc_manager, 'speech_services') and peer_id in webrtc_manager.speech_services:
                speech_service = webrtc_manager.speech_services.pop(peer_id, None)
                if speech_service:
                    await speech_service.close_session(peer_id)
            
            # Clean up silence detection tasks
            if hasattr(websocket.app.state, 'silence_detection_tasks') and peer_id in websocket.app.state.silence_detection_tasks:
                task = websocket.app.state.silence_detection_tasks.pop(peer_id, None)
                if task and not task.done():
                    task.cancel()
            
            # Clean up audio buffers
            audio_buffers.pop(peer_id, None)
            last_speech_timestamps.pop(peer_id, None)
            is_processing.pop(peer_id, None)
            
            # Unregister peer
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