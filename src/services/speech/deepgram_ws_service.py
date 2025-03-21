# services/speech/deepgram_ws_service.py

import logging
import asyncio
import json
import base64
import os
import time
import websockets
from typing import Dict, Optional, Callable, Awaitable, Any, List

logger = logging.getLogger(__name__)

class DeepgramWebSocketService:
    """Service to handle speech-to-text conversion using Deepgram's WebSocket API"""
    
    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        self.deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
        
        if not self.deepgram_api_key:
            logger.warning("DEEPGRAM_API_KEY environment variable not set - speech recognition will fail")
        
        self.ws_url = "wss://api.deepgram.com/v1/listen"
        
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
                "diarize=false",
                "interim_results=false",
                "vad_events=true"
            ]
            
            full_url = f"{self.ws_url}?{'&'.join(query_params)}"
            
            # Initialize the session data structure
            self.active_sessions[session_id] = {
                "callback": callback,
                "buffer": bytearray(),
                "last_activity": time.time(),
                "last_process_time": time.time(),
                "ws_connection": None,
                "connected": False,
                "transcript_buffer": [],
                "is_speaking": False,
                "pending_audio": asyncio.Queue(),
                "processing_task": None
            }
            
            # Create and start the WebSocket connection task
            processing_task = asyncio.create_task(
                self._maintain_connection(session_id, full_url)
            )
            
            self.active_sessions[session_id]["processing_task"] = processing_task
            
            # Wait briefly to ensure connection is established
            for _ in range(20):  # Try for up to 2 seconds
                await asyncio.sleep(0.1)
                if self.active_sessions[session_id]["connected"]:
                    logger.info(f"Deepgram WebSocket connection established for {session_id}")
                    return True
            
            logger.warning(f"Timed out waiting for Deepgram WebSocket connection for {session_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error initializing Deepgram WebSocket session for {session_id}: {str(e)}")
            return False
    
    async def _maintain_connection(self, session_id: str, url: str):
        """Maintain a WebSocket connection to Deepgram, with reconnection logic."""
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries and session_id in self.active_sessions:
            try:
                # Create the header with the API key
                headers = {"Authorization": f"Token {self.deepgram_api_key}"}
                
                # Log connection attempt
                logger.info(f"Connecting to Deepgram WebSocket for {session_id}")
                
                # Connect to the WebSocket with the headers
                async with websockets.connect(url, extra_headers=headers) as websocket:
                    # Update session state
                    session = self.active_sessions[session_id]
                    session["ws_connection"] = websocket
                    session["connected"] = True
                    
                    logger.info(f"Connected to Deepgram WebSocket for {session_id}")
                    
                    # Start the task for sending audio to Deepgram
                    audio_sender = asyncio.create_task(
                        self._process_audio_queue(session_id, websocket)
                    )
                    
                    # Process incoming messages from Deepgram
                    try:
                        while session_id in self.active_sessions:
                            message = await websocket.recv()
                            await self._handle_deepgram_message(session_id, message)
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"Deepgram WebSocket connection closed for {session_id}")
                    except Exception as e:
                        logger.error(f"Error processing Deepgram messages: {str(e)}")
                    finally:
                        # Clean up audio sender task
                        if not audio_sender.done():
                            audio_sender.cancel()
                        
                        # Update session state
                        if session_id in self.active_sessions:
                            self.active_sessions[session_id]["connected"] = False
                            self.active_sessions[session_id]["ws_connection"] = None
            
            except websockets.exceptions.WebSocketException as e:
                retry_count += 1
                logger.error(f"WebSocket error (attempt {retry_count}/{max_retries}): {str(e)}")
                if retry_count < max_retries:
                    await asyncio.sleep(1)  # Wait before retrying
            
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket connection: {str(e)}")
                break
    
    async def _process_audio_queue(self, session_id: str, websocket):
        """Process audio data from the queue and send it to Deepgram."""
        try:
            if session_id not in self.active_sessions:
                return
                
            session = self.active_sessions[session_id]
            queue = session["pending_audio"]
            
            while True:
                # Get audio data from the queue
                audio_data = await queue.get()
                
                # Check for termination signal (None)
                if audio_data is None:
                    break
                
                # Send audio data to Deepgram
                await websocket.send(audio_data)
                
                # Mark task as done
                queue.task_done()
                
                # Small delay to avoid overwhelming the socket
                await asyncio.sleep(0.01)
                
        except asyncio.CancelledError:
            # Task was cancelled, exit cleanly
            logger.debug(f"Audio processing task cancelled for {session_id}")
        except Exception as e:
            logger.error(f"Error in audio queue processing for {session_id}: {str(e)}")
    
    async def _handle_deepgram_message(self, session_id: str, message: str):
        """Handle messages received from the Deepgram WebSocket."""
        try:
            if session_id not in self.active_sessions:
                return
                
            session = self.active_sessions[session_id]
            callback = session.get("callback")
            
            # Ignore if no callback is registered
            if not callback:
                return
                
            # Parse message as JSON
            data = json.loads(message)
            message_type = data.get("type")
            
            if message_type == "Results":
                # Extract transcript from results
                alternatives = data.get("channel", {}).get("alternatives", [])
                
                if alternatives and len(alternatives) > 0:
                    transcript = alternatives[0].get("transcript", "").strip()
                    is_final = data.get("is_final", False)
                    
                    if transcript and is_final:
                        logger.info(f"Final transcript for {session_id}: '{transcript}'")
                        await callback(session_id, transcript)
                        
            elif message_type == "UtteranceEnd":
                logger.debug(f"Utterance end event for {session_id}")
                # Empty string signals utterance end to the handler
                await callback(session_id, "")
                
            elif message_type == "SpeechStarted":
                logger.debug(f"Speech started for {session_id}")
                session["is_speaking"] = True
                
            elif message_type == "SpeechFinished":
                logger.debug(f"Speech finished for {session_id}")
                session["is_speaking"] = False
                
            elif message_type == "Error":
                logger.error(f"Deepgram error: {data}")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Deepgram message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error handling Deepgram message: {str(e)}")
    
    async def process_audio_chunk(self, session_id: str, audio_data: bytes):
        """Process an audio chunk by adding it to the queue for the WebSocket."""
        try:
            if session_id not in self.active_sessions:
                logger.warning(f"No active session for {session_id}")
                return False
                
            session = self.active_sessions[session_id]
            
            # Update last activity time
            session["last_activity"] = time.time()
            
            # If not connected, buffer the audio
            if not session["connected"]:
                # Store in buffer if not connected yet
                session["buffer"].extend(audio_data)
                return True
            
            # Add to processing queue
            await session["pending_audio"].put(audio_data)
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio chunk: {str(e)}")
            return False
    
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes for processing."""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Calculate audio energy (for μ-law encoded audio)
            silence_level = 128  # μ-law silence reference
            non_silent_bytes = sum(1 for b in audio_data if abs(b - silence_level) > 10)
            energy_percentage = (non_silent_bytes / len(audio_data)) * 100
            
            # Only process audio with sufficient energy
            if energy_percentage > 5.0:  # At least 5% non-silent
                return audio_data
            
            return None
            
        except Exception as e:
            logger.error(f"Audio conversion error: {str(e)}")
            return None
    
    async def detect_silence(self, session_id: str, silence_threshold_sec: float = 1.5) -> bool:
        """Check if there has been silence (no new audio) for a specified duration."""
        if session_id not in self.active_sessions:
            return False
            
        current_time = time.time()
        last_activity = self.active_sessions[session_id]["last_activity"]
        
        return (current_time - last_activity) >= silence_threshold_sec
   
    async def close_session(self, session_id: str):
        """Close a speech recognition session and clean up resources."""
        if session_id not in self.active_sessions:
            return False
        
        logger.info(f"Closing Deepgram WebSocket session for {session_id}")
        
        try:
            # Cancel the processing task
            processing_task = self.active_sessions[session_id].get("processing_task")
            if processing_task and not processing_task.done():
                processing_task.cancel()
                try:
                    await processing_task
                except asyncio.CancelledError:
                    pass
            
            # Signal the audio queue to stop
            pending_audio = self.active_sessions[session_id].get("pending_audio")
            if pending_audio:
                await pending_audio.put(None)
            
            # Remove session data
            del self.active_sessions[session_id]
            
            return True
            
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}")
            return False