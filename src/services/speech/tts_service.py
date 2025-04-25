import aiohttp
import asyncio
import base64
import logging
import json
import time
import os
from typing import Optional, AsyncGenerator, Dict, Any, Callable, List
import io
import wave
import audioop
import tempfile
import subprocess

logger = logging.getLogger(__name__)

class WebSocketTTSService:
    def __init__(self):
        """Initialize WebSocket-based ElevenLabs TTS Service"""
        self.voice_id = os.getenv("VOICE_ID", "IKne3meq5aSn9XLyUdCD")
        self.api_key = os.getenv("ELEVEN_LABS_API_KEY")
        self.base_url = "wss://api.elevenlabs.io/v1/text-to-speech"
        self.session = None
        self.ws = None
        self.audio_callback = None
        self.is_connected = False
        self.is_closed = False
        self.connection_lock = asyncio.Lock()
        self.audio_queue = asyncio.Queue()
        self.listener_task = None
        self.has_sent_initial_message = False
        self.buffer = ""
        
        # Validate configuration
        if not self.api_key:
            logger.warning("ElevenLabs API key is not set. TTS services will not work.")
            
    async def stream_text(self, text: str):
        """Stream text to ElevenLabs following API requirements"""
        if not text or not text.strip():
            return True
            
        if not self.is_connected or not self.ws or self.ws.closed:
            logger.warning("Not connected to ElevenLabs, attempting to reconnect")
            success = await self.connect(self.audio_callback)
            if not success:
                return False
                        
        if not self.has_sent_initial_message:
            logger.error("Cannot stream text before initial message is sent")
            return False
        
        try:
            # Add the text to the buffer
            self.buffer += text
            
            # Check if the text contains sentence-ending punctuation
            is_complete_chunk = any(p in text for p in ".!?\"")
            
            # Prepare message according to ElevenLabs documentation
            message = {
                "text": text,
                "try_trigger_generation": is_complete_chunk
            }
            
            logger.info(f"Sending text chunk to ElevenLabs: '{text}'")
            
            # Send the message with a timeout
            await asyncio.wait_for(
                self.ws.send_json(message), 
                timeout=5.0
            )
            
            return True
                
        except asyncio.TimeoutError:
            logger.error("Timeout sending text to ElevenLabs")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Error sending text to ElevenLabs: {str(e)}")
            self.is_connected = False
            return False

    async def _listen_for_audio(self):
        """Listen for audio chunks from ElevenLabs"""
        if not self.ws:
            return
            
        try:
            logger.info("Starting ElevenLabs WebSocket audio listener")
            audio_chunks_received = 0
            start_time = time.time()
            messages_received = 0
            
            async for msg in self.ws:
                if self.is_closed:
                    break
                    
                messages_received += 1
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        
                        # Check for audio chunk
                        if "audio" in data:
                            # Audio is already base64 encoded from ElevenLabs
                            audio_base64 = data["audio"]
                            audio_chunks_received += 1
                            
                            if audio_chunks_received == 1:
                                first_chunk_time = time.time() - start_time
                                logger.info(f"Received first audio chunk: {len(audio_base64)} characters (latency: {first_chunk_time:.2f}s)")
                            
                            # Use callback if provided
                            if self.audio_callback:
                                try:
                                    # Pass the base64 string directly to the callback
                                    await self.audio_callback(audio_base64)
                                except Exception as e:
                                    logger.error(f"Error in audio callback: {str(e)}")
                            
                        # Handle any errors
                        elif "error" in data:
                            logger.error(f"ElevenLabs API error: {data['error']}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON received")
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("ElevenLabs WebSocket closed")
                    break
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    break
            
            logger.info(f"Audio listener summary:")
            logger.info(f"Messages received: {messages_received}")
            logger.info(f"Audio chunks received: {audio_chunks_received}")
            
        except Exception as e:
            logger.error(f"Critical error in audio listener: {str(e)}")
        finally:
            logger.info("ElevenLabs WebSocket audio listener stopped")
    
    
    async def convert_mp3_to_mulaw(self, audio_base64):
        """
        Convert MP3 audio (base64 encoded) to μ-law 8kHz mono format for Twilio
        
        Args:
            audio_base64: Base64 encoded MP3 audio from ElevenLabs
            
        Returns:
            Base64 encoded μ-law audio ready for Twilio
        """
        try:
            # Decode base64 MP3 data
            mp3_data = base64.b64decode(audio_base64)
            
            # Create temporary files
            mp3_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            ulaw_file = tempfile.NamedTemporaryFile(suffix=".ulaw", delete=False)
            
            mp3_path = mp3_file.name
            wav_path = wav_file.name
            ulaw_path = ulaw_file.name
            
            # Close the files so we can use them with ffmpeg
            mp3_file.close()
            wav_file.close()
            ulaw_file.close()
            
            # Write MP3 data to temp file
            with open(mp3_path, "wb") as f:
                f.write(mp3_data)
            
            try:
                # Step 1: Convert MP3 to WAV PCM 16-bit mono 8kHz
                subprocess.run([
                    "ffmpeg",
                    "-i", mp3_path,
                    "-ar", "8000",       # 8kHz sample rate
                    "-ac", "1",          # Mono
                    "-acodec", "pcm_s16le",  # 16-bit PCM
                    wav_path
                ], check=True, capture_output=True)
                
                # Step 2: Convert WAV to μ-law
                subprocess.run([
                    "ffmpeg",
                    "-i", wav_path,
                    "-ar", "8000",
                    "-ac", "1",
                    "-acodec", "pcm_mulaw",  # μ-law encoding
                    ulaw_path
                ], check=True, capture_output=True)
                
                # Read μ-law data, skipping WAV header
                with open(ulaw_path, "rb") as f:
                    # Skip WAV header (44 bytes)
                    f.seek(44)
                    ulaw_data = f.read()
                
                # Convert to base64 for Twilio
                ulaw_base64 = base64.b64encode(ulaw_data).decode("utf-8")
                return ulaw_base64
                
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.error(f"Error using ffmpeg: {e}")
                logger.info("Falling back to Python audio conversion")
                
                # Fallback using Python libraries if ffmpeg isn't available
                
                
                # This is a simplification and may not work perfectly
                # For a production system, ensure ffmpeg is installed
                
                # Create a simplified μ-law conversion
                with open(mp3_path, "rb") as f:
                    pcm_data = f.read()[128:]  # Skip header (approximate)
                
                # Convert to mono, resample to 8kHz, then convert to μ-law
                mono_data = audioop.tomono(pcm_data, 2, 0.5, 0.5)
                resampled_data = audioop.ratecv(mono_data, 2, 1, 44100, 8000, None)[0]
                ulaw_data = audioop.lin2ulaw(resampled_data, 2)
                
                ulaw_base64 = base64.b64encode(ulaw_data).decode("utf-8")
                return ulaw_base64
                
        except Exception as e:
            logger.error(f"Error converting MP3 to μ-law: {e}")
            return None
        finally:
            # Clean up temporary files
            for path in [mp3_path, wav_path, ulaw_path]:
                try:
                    if os.path.exists(path):
                        os.unlink(path)
                except Exception as e:
                    logger.error(f"Error cleaning up temp file {path}: {e}")


    async def connect(self, audio_callback: Callable[[str], Any] = None):
        """Connect to ElevenLabs WebSocket API"""
        async with self.connection_lock:
            # Reset state
            if self.is_connected and self.ws and not self.ws.closed:
                self.audio_callback = audio_callback
                return True
                
            self.audio_callback = audio_callback
            self.is_closed = False
            self.has_sent_initial_message = False
            self.buffer = ""
            
            try:
                # Construct WebSocket URL with precise parameters per documentation
                url = f"{self.base_url}/{self.voice_id}/stream-input"
                params = {
                    "model_id": "eleven_turbo_v2",
                    "output_format": "mp3_44100",
                    "optimize_streaming_latency": "0",
                    "auto_mode": "false",
                    "inactivity_timeout": "30",
                    "sync_alignment": "true"  # Include timing data with audio chunks
                }
                
                # Add query params to URL
                query_string = "&".join(f"{k}={v}" for k, v in params.items())
                full_url = f"{url}?{query_string}"
                
                logger.info(f"Connecting to ElevenLabs WebSocket at {full_url}")
                
                # Create connection
                self.session = aiohttp.ClientSession()
                headers = {
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json"
                }
                
                # Connect to WebSocket
                self.ws = await self.session.ws_connect(
                    full_url, 
                    headers=headers,
                    heartbeat=30.0,
                    receive_timeout=60.0
                )
                
                # Start listener task
                self.listener_task = asyncio.create_task(self._listen_for_audio())
                
                # Initial connection message - MUST be a space
                initial_message = {
                    "text": " ",  # Required initial message per docs
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.8,
                        "speed": 1.0
                    }
                }
                
                await self.ws.send_json(initial_message)
                self.has_sent_initial_message = True
                self.is_connected = True
                
                logger.info("Connected to ElevenLabs WebSocket API")
                return True
                
            except Exception as e:
                logger.error(f"Error connecting to ElevenLabs WebSocket: {str(e)}")
                await self._cleanup()
                return False
            
    async def stream_end(self):
        """Signal end of stream with empty text"""
        if not self.is_connected:
            return False
            
        try:
            # Check if websocket is still open before sending
            if self.ws and not self.ws.closed:
                # According to docs: End the stream with an empty string
                end_message = {"text": ""}
                await self.ws.send_json(end_message)
                return True
            else:
                logger.info("WebSocket already closed, skipping end signal")
                return False
                
        except Exception as e:
            logger.error(f"Error sending end signal to ElevenLabs: {str(e)}")
            self.is_connected = False
            return False
    
    async def flush(self):
        """Force the generation of audio for accumulated text"""
        if not self.is_connected:
            return False
            
        try:
            # Check if websocket is still open
            if self.ws and not self.ws.closed:
                flush_message = {
                    "text": "",
                    "flush": True  # Force generation of any remaining text
                }
                await self.ws.send_json(flush_message)
                return True
            else:
                logger.info("WebSocket closed, cannot flush")
                return False
        except Exception as e:
            logger.error(f"Error flushing ElevenLabs buffer: {str(e)}")
            return False
            
    async def _cleanup(self):
        """Clean up resources"""
        self.is_connected = False
        
        # Cancel listener task
        if self.listener_task and not self.listener_task.done():
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
            self.listener_task = None
        
        # Close WebSocket
        ws = self.ws
        self.ws = None  # Clear reference first
        if ws and not ws.closed:
            try:
                await ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {str(e)}")
        
        # Close session
        session = self.session
        self.session = None  # Clear reference first
        if session and not session.closed:
            try:
                await session.close()
            except Exception as e:
                logger.error(f"Error closing session: {str(e)}")
    
    async def close(self):
        """Close the WebSocket connection"""
        if self.is_closed:
            return  # Already closed, avoid duplicate close
            
        self.is_closed = True
        
        # Try to send end signal
        try:
            if self.is_connected and self.ws and not self.ws.closed:
                # Send empty text to signal end of conversation
                end_message = {"text": ""}
                await self.ws.send_json(end_message)
                await asyncio.sleep(0.5)  # Allow time for processing
        except Exception as e:
            logger.error(f"Error during stream end: {str(e)}")
        
        # Clean up resources
        await self._cleanup()
        logger.info("Closed ElevenLabs WebSocket connection")