# services/speech/deepgram_stt_service.py

import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional, Callable, Dict, Any, List, AsyncGenerator

import aiohttp
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

class DeepgramSTTService:
    """
    Speech-to-Text service using Deepgram's WebSocket API for real-time audio processing.
    Handles speech detection, interim results, and utterance end detection.
    """
    
    def __init__(self):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.ws_url = "wss://api.deepgram.com/v1/listen"
        self.active_sessions = {}
        self.user_speech_buffers = {}
        self.last_activity_times = {}
        self.speech_in_progress = {}
        self.connections = {}
        self.connection_locks = {}
        
        # Validate configuration
        if not self.api_key:
            logger.warning("Deepgram API key is not set. STT services will not work.")
    
    async def create_session(self, session_id: str, transcription_callback: Callable = None) -> bool:
        """
        Create a new Deepgram WebSocket session for streaming audio with proper locking.
        """
        # Create a connection lock for this session if it doesn't exist
        if session_id not in self.connection_locks:
            self.connection_locks[session_id] = asyncio.Lock()
        
        # Use the session-specific lock
        async with self.connection_locks[session_id]:
            if session_id in self.active_sessions:
                logger.warning(f"Session {session_id} already exists. Closing existing session.")
                await self.close_session(session_id)
            
            try:
                # Initialize session state
                self.active_sessions[session_id] = {
                    "transcription_callback": transcription_callback,
                    "buffer": bytearray(),
                    "last_activity": time.time(),
                    "speech_active": False,
                    "interim_transcripts": [],
                    "connection_in_progress": False,  # Add flag to track connection attempts
                    "session_params": {
                        "model": "nova-3",
                        "language": "en-US",
                        "smart_format": "true",
                        "interim_results": "true",
                        "endpointing": "300",
                        "vad_events": "true",
                        "utterance_end_ms": "1000"
                    }
                }
                
                self.user_speech_buffers[session_id] = []
                self.last_activity_times[session_id] = time.time()
                self.speech_in_progress[session_id] = False
                
                # Create WebSocket connection in a separate task
                connection_task = asyncio.create_task(self._maintain_connection(session_id))
                self.active_sessions[session_id]["connection_task"] = connection_task
                
                logger.info(f"Created Deepgram STT session: {session_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error creating Deepgram STT session: {str(e)}")
                return False
            
            
    async def _maintain_connection(self, session_id: str):
        """
        Maintains an active WebSocket connection to Deepgram with proper locking.
        """
        retry_count = 0
        max_retries = 3
        retry_delay = 1.0
        
        # Get the lock for this session
        if session_id not in self.connection_locks:
            self.connection_locks[session_id] = asyncio.Lock()
        
        lock = self.connection_locks[session_id]
        
        while session_id in self.active_sessions and retry_count < max_retries:
            # Check if a connection is already in progress
            if self.active_sessions[session_id].get("connection_in_progress", False):
                await asyncio.sleep(0.5)  # Wait before checking again
                continue
                
            async with lock:
                try:
                    # Mark connection as in progress
                    self.active_sessions[session_id]["connection_in_progress"] = True
                    
                    # Check if we already have a working connection
                    if (session_id in self.connections and 
                        "ws" in self.connections[session_id] and 
                        not self.connections[session_id]["ws"].closed):
                        # Connection is already established
                        self.active_sessions[session_id]["connection_in_progress"] = False
                        return
                    
                    # Connect to WebSocket
                    await self._connect_websocket(session_id)
                    
                    # If connection was successful, reset retry count
                    retry_count = 0
                    self.active_sessions[session_id]["connection_in_progress"] = False
                    
                except Exception as e:
                    retry_count += 1
                    self.active_sessions[session_id]["connection_in_progress"] = False
                    logger.error(f"WebSocket connection error for session {session_id}: {str(e)}")
                    logger.info(f"Retrying connection in {retry_delay} seconds (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        
        if retry_count >= max_retries:
            logger.error(f"Failed to maintain connection for session {session_id} after {max_retries} retries")
            await self.close_session(session_id)
            
            
    async def _connect_websocket(self, session_id: str):
        """Establish WebSocket connection to Deepgram and set up message handler"""
        session_data = self.active_sessions[session_id]
        params = session_data["session_params"]
        
        # Build URL with parameters
        query_params = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{self.ws_url}?{query_params}"
        
        logger.info(f"Connecting to Deepgram at {full_url} for session {session_id}")
        
        # Create session and connect to WebSocket
        session = aiohttp.ClientSession()
        headers = {"Authorization": f"Token {self.api_key}"}
        
        try:
            ws = await session.ws_connect(
                full_url,
                headers=headers,
                heartbeat=30.0,
                receive_timeout=60.0
            )
            
            # Store connection objects
            self.connections[session_id] = {
                "session": session,
                "ws": ws
            }
            
            # Start listener task
            asyncio.create_task(self._listen_for_messages(session_id, ws))
            
            logger.info(f"Connected to Deepgram STT WebSocket for session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection error: {str(e)}")
            if session and not session.closed:
                await session.close()
            return False
    
    async def _listen_for_messages(self, session_id: str, ws):
        """Listen for messages from Deepgram WebSocket"""
        try:
            logger.info(f"Starting Deepgram message listener for session {session_id}")
            
            async for msg in ws:
                if session_id not in self.active_sessions:
                    logger.info(f"Session {session_id} closed, stopping listener")
                    break
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text_message(session_id, msg.data)
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error for session {session_id}: {msg.data}")
                    break
                    
            logger.info(f"WebSocket message loop ended for session {session_id}")
            
        except ConnectionClosed:
            logger.warning(f"WebSocket connection closed for session {session_id}")
            
        except Exception as e:
            logger.error(f"Error in WebSocket listener for session {session_id}: {str(e)}")
            
        finally:
            # If we exit the listener loop, attempt to reconnect
            if session_id in self.active_sessions:
                logger.info(f"Attempting to reconnect session {session_id}")
                asyncio.create_task(self._maintain_connection(session_id))
    
    async def _handle_text_message(self, session_id: str, message_data: str):
        """Handle text messages from Deepgram WebSocket"""
        try:
            data = json.loads(message_data)
            message_type = data.get("type")
            
            # Update last activity time
            if session_id in self.last_activity_times:
                self.last_activity_times[session_id] = time.time()
            
            if message_type == "Results":
                await self._handle_results(session_id, data)
                
            elif message_type == "SpeechStarted":
                await self._handle_speech_started(session_id, data)
                
            elif message_type == "UtteranceEnd":
                await self._handle_utterance_end(session_id, data)
                
            elif message_type == "Metadata":
                logger.debug(f"Received metadata for session {session_id}: {data}")
                
            else:
                logger.debug(f"Received unknown message type for session {session_id}: {message_type}")
                
        except json.JSONDecodeError:
            logger.warning(f"Received invalid JSON for session {session_id}")
            
        except Exception as e:
            logger.error(f"Error handling message for session {session_id}: {str(e)}")
    
    async def _handle_results(self, session_id: str, data):
        """Handle transcription results from Deepgram"""
        if session_id not in self.active_sessions:
            return
            
        # Extract transcript if available
        try:
            alternatives = data.get("channel", {}).get("alternatives", [])
            if alternatives and len(alternatives) > 0:
                transcript = alternatives[0].get("transcript", "").strip()
                is_final = data.get("is_final", False)
                speech_final = data.get("speech_final", False)
                
                # Only process non-empty transcripts
                if transcript:
                    logger.debug(f"Session {session_id} received transcript: '{transcript}' (final: {is_final}, speech_final: {speech_final})")
                    
                    session = self.active_sessions[session_id]
                    
                    # Store interim results for potential future use
                    if not is_final:
                        session["interim_transcripts"] = transcript
                    
                    # If the transcript is final or speech_final is true, send it to the callback
                    # speech_final = true indicates natural pause detected by endpointing
                    if speech_final or is_final:
                        # Add to speech buffer for processing
                        if session_id in self.user_speech_buffers and transcript not in self.user_speech_buffers[session_id]:
                            self.user_speech_buffers[session_id].append(transcript)
                            logger.info(f"Added to speech buffer for session {session_id}: '{transcript}'")
                        
                        # If we have a callback, call it with empty text to trigger processing
                        # This will let the caller know we have complete transcripts ready
                        callback = session.get("transcription_callback")
                        if callback:
                            await callback(session_id, "")
                
        except Exception as e:
            logger.error(f"Error handling results for session {session_id}: {str(e)}")
    
    async def _handle_speech_started(self, session_id: str, data):
        """Handle speech started events from Deepgram"""
        if session_id not in self.active_sessions:
            return
            
        try:
            timestamp = data.get("timestamp", 0)
            logger.info(f"Speech started detected for session {session_id} at {timestamp}s")
            
            # Mark speech as active
            self.speech_in_progress[session_id] = True
            self.active_sessions[session_id]["speech_active"] = True
            
        except Exception as e:
            logger.error(f"Error handling speech started for session {session_id}: {str(e)}")
    
    async def _handle_utterance_end(self, session_id: str, data):
        """Handle utterance end events from Deepgram"""
        if session_id not in self.active_sessions:
            return
            
        try:
            last_word_end = data.get("last_word_end", 0)
            logger.info(f"Utterance end detected for session {session_id} at {last_word_end}s")
            
            # Mark speech as inactive
            self.speech_in_progress[session_id] = False
            self.active_sessions[session_id]["speech_active"] = False
            
            # If we have any buffered speech, process it now
            if session_id in self.user_speech_buffers and self.user_speech_buffers[session_id]:
                callback = self.active_sessions[session_id].get("transcription_callback")
                if callback:
                    await callback(session_id, "")
            
        except Exception as e:
            logger.error(f"Error handling utterance end for session {session_id}: {str(e)}")
    
    async def process_audio_chunk(self, session_id: str, audio_data: bytes, 
                                 callback: Optional[Callable[[str, str], Any]] = None):
        """
        Process an audio chunk for a session with proper connection handling
        """
        try:
            if session_id not in self.active_sessions:
                # Initialize new session if it doesn't exist
                await self.create_session(session_id, callback)
            elif callback and not self.active_sessions[session_id]["transcription_callback"]:
                # Update callback if it wasn't set initially
                self.active_sessions[session_id]["transcription_callback"] = callback
            
            # Update activity time
            self.active_sessions[session_id]["last_activity"] = time.time()
            self.last_activity_times[session_id] = time.time()
            
            # Get the connection lock for this session
            if session_id not in self.connection_locks:
                self.connection_locks[session_id] = asyncio.Lock()
            
            # Check if we have an active connection
            async with self.connection_locks[session_id]:
                if session_id in self.connections and "ws" in self.connections[session_id]:
                    ws = self.connections[session_id]["ws"]
                    if not ws.closed:
                        await ws.send_bytes(audio_data)
                        return True
            
            # If we don't have an active connection or it's closed, buffer the audio
            # until the connection is established
            self.active_sessions[session_id]["buffer"] += audio_data
            
            # Check if a connection is already in progress
            if not self.active_sessions[session_id].get("connection_in_progress", False):
                # Start a new connection if one isn't already in progress
                asyncio.create_task(self._maintain_connection(session_id))
            
            return False
            
        except Exception as e:
            logger.error(f"Error processing audio chunk for session {session_id}: {str(e)}")
            return False
        
        
    async def process_final_buffer(self, session_id: str, callback: Optional[Callable] = None):
        """Process any remaining audio in the buffer when a session ends"""
        if session_id not in self.active_sessions:
            return False
            
        try:
            # Send Finalize message to process any remaining audio
            if session_id in self.connections and "ws" in self.connections[session_id]:
                ws = self.connections[session_id]["ws"]
                if not ws.closed:
                    # Send Finalize message
                    finalize_msg = json.dumps({"type": "Finalize"})
                    await ws.send_str(finalize_msg)
                    logger.info(f"Sent Finalize message for session {session_id}")
                    
                    # Give Deepgram a moment to process
                    await asyncio.sleep(0.5)
                    
                    # Process any buffered transcripts
                    if session_id in self.user_speech_buffers and self.user_speech_buffers[session_id]:
                        combined_speech = " ".join(self.user_speech_buffers[session_id])
                        self.user_speech_buffers[session_id] = []
                        
                        if callback:
                            await callback(session_id, combined_speech)
                        elif self.active_sessions[session_id]["transcription_callback"]:
                            await self.active_sessions[session_id]["transcription_callback"](session_id, combined_speech)
                    
                    # Send CloseStream message to gracefully close
                    close_msg = json.dumps({"type": "CloseStream"})
                    await ws.send_str(close_msg)
                    logger.info(f"Sent CloseStream message for session {session_id}")
                    
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error processing final buffer for session {session_id}: {str(e)}")
            return False
    
    async def close_session(self, session_id: str):
        """Close a speech recognition session with proper locking"""
        if session_id not in self.active_sessions:
            return False
            
        # Get the lock for this session
        if session_id in self.connection_locks:
            lock = self.connection_locks[session_id]
        else:
            # Create a lock if one doesn't exist
            self.connection_locks[session_id] = asyncio.Lock()
            lock = self.connection_locks[session_id]
        
        async with lock:
            try:
                logger.info(f"Closing Deepgram STT session: {session_id}")
                
                # Cancel connection task if it exists
                connection_task = self.active_sessions[session_id].get("connection_task")
                if connection_task and not connection_task.done():
                    connection_task.cancel()
                    try:
                        await connection_task
                    except asyncio.CancelledError:
                        pass
                
                # Send CloseStream message if WebSocket is still open
                if session_id in self.connections and "ws" in self.connections[session_id]:
                    ws = self.connections[session_id]["ws"]
                    if not ws.closed:
                        try:
                            close_msg = json.dumps({"type": "CloseStream"})
                            await ws.send_str(close_msg)
                            logger.info(f"Sent CloseStream message for session {session_id}")
                        except:
                            pass
                        
                        try:
                            await ws.close()
                        except:
                            pass
                
                # Close the aiohttp session
                if session_id in self.connections and "session" in self.connections[session_id]:
                    session = self.connections[session_id]["session"]
                    if not session.closed:
                        await session.close()
                
                # Clean up session data
                self.connections.pop(session_id, None)
                self.active_sessions.pop(session_id, None)
                self.user_speech_buffers.pop(session_id, None)
                self.last_activity_times.pop(session_id, None)
                self.speech_in_progress.pop(session_id, None)
                self.connection_locks.pop(session_id, None)
                
                logger.info(f"Closed speech recognition session {session_id}")
                return True
                
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {str(e)}")
                return False
    
    
    async def get_completed_speech(self, session_id: str):
        """Get all completed speech for a session"""
        if session_id not in self.user_speech_buffers:
            return ""
            
        combined_speech = " ".join(self.user_speech_buffers[session_id])
        self.user_speech_buffers[session_id] = []
        return combined_speech
    
    async def is_speech_active(self, session_id: str):
        """Check if speech is currently active for a session"""
        return self.speech_in_progress.get(session_id, False)
    
    async def detect_silence(self, session_id: str, threshold: float = 1.5):
        """Check if there has been silence for a specified duration"""
        if session_id not in self.last_activity_times:
            return False
            
        current_time = time.time()
        last_activity = self.last_activity_times[session_id]
        
        return (current_time - last_activity) >= threshold
    
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes"""
        if not base64_payload:
            return None
            
        try:
            # Decode base64 audio - Twilio's audio is μ-law format at 8kHz
            audio_data = base64.b64decode(base64_payload)
            
            # Only log for large chunks to reduce log volume
            if len(audio_data) > 1000:
                logger.debug(f"Converted {len(base64_payload)} chars of base64 to {len(audio_data)} bytes for session {session_id}")
                
            return audio_data
            
        except Exception as e:
            logger.error(f"Error converting Twilio audio for session {session_id}: {str(e)}")
            return None