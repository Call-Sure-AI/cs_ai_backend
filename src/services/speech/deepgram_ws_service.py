# services/speech/deepgram_ws_service.py

import logging
import asyncio
import json
import base64
import os
import time
import websockets
from typing import Dict, Optional, Callable, Awaitable, Any

logger = logging.getLogger(__name__)

class DeepgramWebSocketService:
    """Service to handle speech-to-text conversion using Deepgram's WebSocket API"""
    
    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        self.deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
        
        if not self.deepgram_api_key:
            logger.warning("DEEPGRAM_API_KEY environment variable not set - speech recognition will fail")
        else:
            # Log first 4 characters of API key for debugging
            masked_key = self.deepgram_api_key[:4] + "..." if len(self.deepgram_api_key) > 4 else "too_short"
            logger.info(f"Deepgram initialized with API key starting with: {masked_key}")
        
        self.ws_base_url = "wss://api.deepgram.com/v1/listen"
        
    async def initialize_session(self, session_id: str, 
                              callback: Optional[Callable[[str, str], Awaitable[Any]]] = None) -> bool:
        """Initialize a new Deepgram WebSocket session."""
        try:
            if session_id in self.active_sessions:
                # Close existing connection if there is one
                await self.close_session(session_id)
            
            logger.info(f"Initializing new Deepgram WebSocket session for {session_id}")
            
            # Build the URL with query parameters
            query_params = [
                "model=nova-3",
                "endpointing=true",
                "punctuate=true",
                "smart_format=true",
                "filler_words=false",
                "interim_results=false"
            ]
            
            # Store session info
            self.active_sessions[session_id] = {
                "callback": callback,
                "url": f"{self.ws_base_url}?{'&'.join(query_params)}",
                "websocket": None,
                "connected": False,
                "buffer": bytearray(),
                "last_activity": time.time(),
                "task": None
            }
            
            # Start the connection management task
            session = self.active_sessions[session_id]
            session["task"] = asyncio.create_task(self._ws_session_handler(session_id))
            
            # Wait for connection to establish
            for _ in range(30):  # Wait up to 3 seconds
                if session_id not in self.active_sessions:
                    return False
                    
                if self.active_sessions[session_id]["connected"]:
                    logger.info(f"Deepgram WebSocket connected for {session_id}")
                    return True
                    
                await asyncio.sleep(0.1)
            
            logger.warning(f"Timed out waiting for Deepgram connection for {session_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error initializing Deepgram session: {str(e)}")
            return False
            
    async def _ws_session_handler(self, session_id: str):
        """Handle the WebSocket session to Deepgram."""
        websocket = None
        
        try:
            if session_id not in self.active_sessions:
                return
                
            session = self.active_sessions[session_id]
            url = session["url"]
            
            # For websockets 15.0, we create extra_headers as a dict
            extra_headers = {
                "Authorization": f"Token {self.deepgram_api_key}"
            }
            
            # Log connection attempt with masked API key (first 4 chars only)
            masked_key = self.deepgram_api_key[:4] + "..." if self.deepgram_api_key else "None"
            logger.info(f"Connecting to Deepgram with API key starting with {masked_key}")
            
            # Connect with proper headers for websockets 15.0
            websocket = await websockets.connect(
                url, 
                extra_headers=extra_headers
            )
            
            # Update session
            session["websocket"] = websocket
            session["connected"] = True
            
            logger.info(f"Connected to Deepgram WebSocket for {session_id}")
            
            # Process messages from Deepgram
            while session_id in self.active_sessions:
                try:
                    message = await websocket.recv()
                    await self._process_message(session_id, message)
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"Deepgram WebSocket connection closed: {str(e)}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving message: {str(e)}")
                    break
                    
        except Exception as e:
            logger.error(f"WebSocket session error: {str(e)}")
        finally:
            # Clean up on exit
            if websocket:
                try:
                    await websocket.close()
                except Exception:
                    pass
                    
            if session_id in self.active_sessions:
                self.active_sessions[session_id]["connected"] = False
                self.active_sessions[session_id]["websocket"] = None
                
    async def _process_message(self, session_id: str, message: str):
        """Process messages from Deepgram."""
        try:
            if session_id not in self.active_sessions:
                return
                
            session = self.active_sessions[session_id]
            callback = session.get("callback")
            
            if not callback:
                return
                
            # Parse JSON response
            data = json.loads(message)
            message_type = data.get("type")
            
            logger.debug(f"Received message type: {message_type}")
            
            # Process different types of messages
            if message_type == "Results":
                # Get transcript from results
                channel_data = data.get("channel", {})
                alternatives = channel_data.get("alternatives", [])
                
                if alternatives and len(alternatives) > 0:
                    transcript = alternatives[0].get("transcript", "").strip()
                    is_final = data.get("is_final", False)
                    
                    if transcript and is_final:
                        logger.info(f"Final transcript for {session_id}: '{transcript}'")
                        await callback(session_id, transcript)
            
            elif message_type == "UtteranceEnd":
                logger.debug(f"Utterance end detected for {session_id}")
                await callback(session_id, "")  # Empty string signals utterance end
                
            elif message_type == "Error":
                logger.error(f"Deepgram error: {data}")
                
            # For debugging - log metadata responses
            elif message_type == "Metadata":
                logger.debug(f"Received Deepgram metadata")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            
    async def process_audio_chunk(self, session_id: str, audio_data: bytes):
        """Process an audio chunk through Deepgram."""
        try:
            if session_id not in self.active_sessions:
                return False
                
            session = self.active_sessions[session_id]
            websocket = session.get("websocket")
            
            # Update last activity time
            session["last_activity"] = time.time()
            
            # If connected, send directly
            if session["connected"] and websocket:
                try:
                    await websocket.send(audio_data)
                    return True
                except Exception as e:
                    logger.error(f"Error sending audio to Deepgram: {str(e)}")
                    return False
                
            # Otherwise store in buffer
            session["buffer"].extend(audio_data)
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio chunk: {str(e)}")
            return False
            
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes for processing."""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Rudimentary energy detection
            silence = 128  # μ-law silence level
            non_silent = sum(1 for b in audio_data if abs(b - silence) > 10)
            
            # Check if audio has enough energy
            if non_silent / len(audio_data) > 0.05:  # 5% non-silent threshold
                return audio_data
                
            return None
            
        except Exception as e:
            logger.error(f"Audio conversion error: {str(e)}")
            return None
            
    async def detect_silence(self, session_id: str, silence_threshold_sec: float = 1.5) -> bool:
        """Check if there has been silence for a specified duration."""
        if session_id not in self.active_sessions:
            return False
            
        current_time = time.time()
        last_activity = self.active_sessions[session_id]["last_activity"]
        
        return (current_time - last_activity) >= silence_threshold_sec
        
    async def close_session(self, session_id: str):
        """Close a speech recognition session."""
        if session_id not in self.active_sessions:
            return False
            
        logger.info(f"Closing Deepgram session for {session_id}")
        
        try:
            # Close WebSocket if connected
            websocket = self.active_sessions[session_id].get("websocket")
            if websocket:
                await websocket.close()
                
            # Cancel task if running
            task = self.active_sessions[session_id].get("task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
            # Remove session
            del self.active_sessions[session_id]
            return True
            
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}")
            return False