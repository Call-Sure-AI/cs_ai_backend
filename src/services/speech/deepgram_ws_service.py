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
                self._manage_websocket_connection(session_id, full_url)
            )
            
            self.active_sessions[session_id]["processing_task"] = processing_task
            
            # Wait briefly to ensure connection is established
            for _ in range(10):  # Try for up to 1 second
                await asyncio.sleep(0.1)
                if self.active_sessions[session_id]["connected"]:
                    logger.info(f"Deepgram WebSocket connection established for {session_id}")
                    return True
            
            logger.warning(f"Timed out waiting for Deepgram WebSocket connection for {session_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error initializing Deepgram WebSocket session for {session_id}: {str(e)}")
            return False
    
    async def _manage_websocket_connection(self, session_id: str, url: str):
        """Manage the WebSocket connection to Deepgram."""
        try:
            session = self.active_sessions[session_id]
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    extra_headers = {
                        "Authorization": f"Token {self.deepgram_api_key}"
                    }
                    
                    async with websockets.connect(url, extra_headers=extra_headers) as websocket:
                        logger.info(f"Connected to Deepgram WebSocket for {session_id}")
                        session["ws_connection"] = websocket
                        session["connected"] = True
                        
                        # Start the audio sending task
                        audio_sender_task = asyncio.create_task(
                            self._send_audio_to_deepgram(session_id, websocket)
                        )
                        
                        # Process incoming messages
                        while True:
                            try:
                                message = await websocket.recv()
                                await self._process_deepgram_message(session_id, message)
                            except websockets.exceptions.ConnectionClosed:
                                logger.warning(f"Deepgram WebSocket connection closed for {session_id}")
                                break
                            except Exception as e:
                                logger.error(f"Error processing Deepgram message for {session_id}: {str(e)}")
                        
                        # Cancel the audio sender task
                        audio_sender_task.cancel()
                        try:
                            await audio_sender_task
                        except asyncio.CancelledError:
                            pass
                        
                        # Connection closed normally, break retry loop
                        break
                        
                except (websockets.exceptions.InvalidStatusCode, 
                        websockets.exceptions.ConnectionClosedError) as e:
                    retry_count += 1
                    logger.error(f"Deepgram WebSocket connection error (retry {retry_count}/{max_retries}): {str(e)}")
                    
                    if retry_count < max_retries:
                        await asyncio.sleep(1)  # Wait before retrying
                    else:
                        logger.error(f"Max retries reached for Deepgram WebSocket connection for {session_id}")
                        break
                        
        except Exception as e:
            logger.error(f"Error in WebSocket connection manager for {session_id}: {str(e)}")
        finally:
            # Mark the session as disconnected
            if session_id in self.active_sessions:
                self.active_sessions[session_id]["connected"] = False
                self.active_sessions[session_id]["ws_connection"] = None
    
    async def _send_audio_to_deepgram(self, session_id: str, websocket):
        """Send audio data to Deepgram WebSocket."""
        try:
            session = self.active_sessions[session_id]
            pending_audio = session["pending_audio"]
            
            while True:
                # Get audio data from the queue
                audio_data = await pending_audio.get()
                
                if not audio_data:  # Empty data signals end
                    break
                
                # Send the audio data to Deepgram
                await websocket.send(audio_data)
                
                # Mark the task as done
                pending_audio.task_done()
                
                # Small delay to avoid overwhelming the WebSocket
                await asyncio.sleep(0.01)
                
        except asyncio.CancelledError:
            logger.info(f"Audio sender task cancelled for {session_id}")
        except Exception as e:
            logger.error(f"Error in audio sender task for {session_id}: {str(e)}")
    
    async def _process_deepgram_message(self, session_id: str, message: str):
        """Process messages received from Deepgram WebSocket."""
        try:
            session = self.active_sessions[session_id]
            callback = session.get("callback")
            
            # Parse the JSON message
            data = json.loads(message)
            
            # Log message type for debugging
            message_type = data.get("type")
            
            if message_type == "Results":
                # Extract transcript from results
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])
                
                if alternatives:
                    # Get the first alternative (highest confidence)
                    transcript = alternatives[0].get("transcript", "").strip()
                    is_final = data.get("is_final", False)
                    speech_final = data.get("speech_final", False)
                    
                    if transcript and is_final and callback:
                        # Call the callback with the transcript
                        logger.info(f"Final transcript for {session_id}: '{transcript}'")
                        await callback(session_id, transcript)
                    
                    # For debugging
                    if is_final:
                        logger.debug(f"Deepgram final result: '{transcript}', speech_final={speech_final}")
                    
            elif message_type == "UtteranceEnd":
                # Utterance has ended, process any buffered transcript
                logger.debug(f"Utterance end detected for {session_id}")
                
                # Signal that speech has ended
                if callback:
                    await callback(session_id, "")
            
            elif message_type == "SpeechStarted":
                logger.debug(f"Speech started detected for {session_id}")
                session["is_speaking"] = True
                
            elif message_type == "SpeechFinished":
                logger.debug(f"Speech finished detected for {session_id}")
                session["is_speaking"] = False
                
            elif message_type == "Metadata":
                logger.debug(f"Received metadata from Deepgram: {data}")
                
            elif message_type == "Error":
                logger.error(f"Deepgram error for {session_id}: {data}")
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Deepgram message for {session_id}: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing Deepgram message for {session_id}: {str(e)}")
    
    async def process_audio_chunk(self, session_id: str, audio_data: bytes):
        """Process an audio chunk by sending it to Deepgram."""
        try:
            if session_id not in self.active_sessions:
                logger.warning(f"No active session found for {session_id}")
                return False
            
            session = self.active_sessions[session_id]
            
            if not session.get("connected"):
                logger.warning(f"WebSocket not connected for {session_id}")
                return False
            
            # Update last activity time
            session["last_activity"] = time.time()
            
            # Add audio to the queue to be sent
            await session["pending_audio"].put(audio_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio chunk for {session_id}: {str(e)}")
            return False
    
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes for processing."""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Detailed energy calculation for μ-law audio
            silence_level = 128  # μ-law silence reference
            non_silent_bytes = [abs(b - silence_level) for b in audio_data]
            
            # More nuanced silence detection
            threshold = 10  # Adjust this value to fine-tune silence detection
            active_bytes = [b for b in non_silent_bytes if b > threshold]
            
            # Calculate energy metrics
            total_bytes = len(audio_data)
            active_count = len(active_bytes)
            silence_percentage = (total_bytes - active_count) / total_bytes * 100
            
            # Enhanced logging - only log if significant audio is detected
            if active_count / total_bytes > 0.1:  # At least 10% active signal
                logger.debug(
                    f"Audio energy for {session_id}: "
                    f"Active: {active_count}/{total_bytes} bytes "
                    f"({100-silence_percentage:.1f}% speech)"
                )
            
            # Return audio if it has enough speech energy
            if active_count / total_bytes > 0.05:  # At least 5% active signal
                return audio_data
            
            return None
            
        except Exception as e:
            logger.error(f"Audio conversion error for {session_id}: {str(e)}")
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
            if processing_task:
                processing_task.cancel()
                try:
                    await processing_task
                except asyncio.CancelledError:
                    pass
            
            # Close the WebSocket connection
            ws_connection = self.active_sessions[session_id].get("ws_connection")
            if ws_connection:
                await ws_connection.close()
            
            # Clear the session data
            del self.active_sessions[session_id]
            
            return True
            
        except Exception as e:
            logger.error(f"Error closing Deepgram WebSocket session for {session_id}: {str(e)}")
            return False