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
        
    async def initialize_session(self, session_id: str, callback: Optional[Callable[[str, str], Awaitable[Any]]] = None) -> bool:
        """Initialize a new Deepgram WebSocket session."""
        try:
            if session_id in self.active_sessions:
                # Close existing connection if there is one
                await self.close_session(session_id)
            api_key_prefix = self.deepgram_api_key[:4] + "..." if self.deepgram_api_key else "None"
            logger.info(f"Initializing Deepgram WebSocket with API key: {api_key_prefix}")
            logger.info(f"Initializing new Deepgram WebSocket session for {session_id}")
            #djflkdsgdnf
            # Build the URL with query parameters
            query_params = [
                "model=nova-3",
                "endpointing=true",
                "punctuate=true",
                "smart_format=true",
                "filler_words=false",
                "interim_results=false",
                "encoding=linear16",  # Add encoding type (e.g., 'linear16')
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
            for _ in range(60):  # Wait up to 6 seconds to establish the connection
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
        retries = 3  # Set the retry count

        try:
            if session_id not in self.active_sessions:
                return
            
            session = self.active_sessions[session_id]
            url = session["url"]

            # Set up the headers
            headers = {
                "Authorization": f"Token {self.deepgram_api_key}"
            }

            logger.info(f"Connecting to Deepgram WebSocket for {session_id}")
            
            # Retry WebSocket connection if needed
            for attempt in range(retries):
                try:
                    websocket = await websockets.connect(
                        url,
                        extra_headers=headers  # For websockets < 10.0
                    )
                    session["websocket"] = websocket
                    session["connected"] = True
                    logger.info(f"Connected to Deepgram WebSocket for {session_id}")
                    break  # Connection successful, exit the retry loop
                except websockets.exceptions.WebSocketException as e:
                    logger.warning(f"WebSocket connection attempt {attempt + 1} failed: {str(e)}")
                    if attempt == retries - 1:
                        logger.error(f"Failed to connect to Deepgram WebSocket after {retries} attempts")
                        return

                    await asyncio.sleep(2 ** attempt)  # Exponential backoff for retries

        except Exception as e:
            logger.error(f"Error initializing WebSocket session: {str(e)}")


            
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
            
    async def process_audio_chunk(self, session_id: str, client_id: str, audio_data: bytes):
        """Process an audio chunk through Deepgram."""
        try:
            if session_id not in self.active_sessions:
                return False
            logger.info(f"Processing audio chunk for {client_id}: {len(audio_data)} bytes")
            session = self.active_sessions[session_id]
            websocket = session.get("websocket")

            if session["connected"] and websocket:
                try:
                    await websocket.send(audio_data)  # Send raw audio data here
                    logger.info(f"Audio chunk sent to Deepgram for {client_id}")
                    return True
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"WebSocket connection closed while sending audio: {str(e)}")
                    # Attempt to reconnect or handle the closed connection
                    await self.reconnect_websocket(session_id)
                    return False
                except Exception as e:
                    logger.error(f"Error sending audio to Deepgram: {str(e)}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error processing audio chunk: {str(e)}")
            return False

    
          
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes"""
        try:
            # Ensure we're working with a string, not bytes
            if isinstance(base64_payload, bytes):
                base64_payload = base64_payload.decode('utf-8')
                
            # Add detailed logging
            logger.info(f"Converting Twilio audio for {session_id}: payload length={len(base64_payload)}")
            
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            logger.info(f"Decoded audio data: {len(audio_data)} bytes")
            
            # Basic noise analysis
            if len(audio_data) < 10:
                logger.warning(f"Audio chunk too small: {len(audio_data)} bytes")
                return None
                
            # Calculate basic audio statistics for debugging
            audio_bytes = [b for b in audio_data]
            min_val = min(audio_bytes) if audio_bytes else 0
            max_val = max(audio_bytes) if audio_bytes else 0
            avg_val = sum(audio_bytes) / len(audio_bytes) if audio_bytes else 0
            
            logger.info(f"Audio stats for {session_id}: min={min_val}, max={max_val}, avg={avg_val:.2f}")
            
            # Return the decoded audio
            return audio_data
            
        except Exception as e:
            logger.error(f"Error converting Twilio audio for {session_id}: {str(e)}")
            return None
    
    async def detect_silence(self, session_id: str, silence_threshold_sec: float = 1.5) -> bool:
        """Check if there has been silence for a specified duration."""
        if session_id not in self.active_sessions:
            return False

        current_time = time.time()
        last_activity = self.active_sessions[session_id]["last_activity"]
        
        # Trigger processing if silence threshold is met
        if (current_time - last_activity) >= silence_threshold_sec:
            logger.debug(f"Silence detected for {session_id}, sending current buffer")
            return True
        return False

        
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