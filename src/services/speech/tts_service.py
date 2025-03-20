# In services/speech/tts_service.py

import aiohttp
import asyncio
import base64
import logging
import json
import time
import os
from typing import Optional, AsyncGenerator, Dict, Any, Callable, List

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
        
        # Validate configuration
        if not self.api_key:
            logger.warning("ElevenLabs API key is not set. TTS services will not work.")
            
    async def __aenter__(self):
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def connect(self, audio_callback: Callable[[bytes], Any] = None):
        """
        Connect to ElevenLabs WebSocket API
        """
        async with self.connection_lock:
            # Reset state
            if self.is_connected:
                await self.close()
                
            self.audio_callback = audio_callback
            self.is_closed = False
            
            try:
                # Construct WebSocket URL with parameters
                url = f"{self.base_url}/{self.voice_id}/stream-input"
                params = {
                    "model_id": "eleven_turbo_v2",  # Use turbo model
                    "output_format": "mulaw_8000",  # Twilio format
                    "optimize_streaming_latency": "3",  # Max optimization
                }
                
                # Add query params to URL
                query_string = "&".join(f"{k}={v}" for k, v in params.items())
                full_url = f"{url}?{query_string}"
                
                logger.info(f"Connecting to ElevenLabs WebSocket at {full_url}")
                
                # Create a new session for this connection
                self.session = aiohttp.ClientSession()
                headers = {"xi-api-key": self.api_key}
                
                # Connect to WebSocket
                self.ws = await self.session.ws_connect(
                    full_url, 
                    headers=headers,
                    heartbeat=30.0,  # Keep the connection alive with heartbeats
                    receive_timeout=60.0  # Longer timeout
                )
                
                # Start listener task
                self.listener_task = asyncio.create_task(self._listen_for_audio())
                
                # Initialize connection with empty text
                voice_settings = {
                    "stability": 0.3,  # Lower for faster responses
                    "similarity_boost": 0.5,  # Lower for faster responses 
                    "speed": 1.0,  # Normal speed
                }
                
                # Send initial message
                init_message = {
                    "text": " ",  # Required initial space
                    "voice_settings": voice_settings
                }
                
                await self.ws.send_json(init_message)
                self.is_connected = True
                logger.info("Connected to ElevenLabs WebSocket API")
                
                return True
                
            except Exception as e:
                logger.error(f"Error connecting to ElevenLabs WebSocket: {str(e)}")
                await self._cleanup()
                return False
    
    async def _listen_for_audio(self):
        """Listen for audio chunks from ElevenLabs"""
        if not self.ws:
            return
            
        try:
            logger.info("Starting ElevenLabs WebSocket audio listener")
            
            async for msg in self.ws:
                if self.is_closed:
                    break
                    
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        
                        # Check if this is an audio chunk
                        if "audio" in data:
                            # Decode base64 audio
                            audio_bytes = base64.b64decode(data["audio"])
                            
                            # Put in queue if callback isn't set
                            if self.audio_callback:
                                try:
                                    await self.audio_callback(audio_bytes)
                                except Exception as e:
                                    logger.error(f"Error in audio callback: {str(e)}")
                            else:
                                await self.audio_queue.put(audio_bytes)
                                
                        # Debug any other messages
                        else:
                            logger.debug(f"ElevenLabs non-audio message: {data}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"Non-JSON response from ElevenLabs: {msg.data}")
                        
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("ElevenLabs WebSocket closed")
                    break
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"ElevenLabs WebSocket error: {msg.data}")
                    break
                    
        except asyncio.CancelledError:
            logger.info("ElevenLabs WebSocket listener task cancelled")
            
        except Exception as e:
            logger.error(f"Error in ElevenLabs WebSocket listener: {str(e)}")
            
        finally:
            logger.info("ElevenLabs WebSocket audio listener stopped")
    
    async def stream_text(self, text: str):
        """
        Stream text to ElevenLabs for TTS generation
        
        Args:
            text: Text chunk to send
        """
        if not self.is_connected:
            logger.warning("Not connected to ElevenLabs, attempting to reconnect")
            success = await self.connect(self.audio_callback)
            if not success:
                logger.error("Failed to reconnect to ElevenLabs")
                return False
        
        try:
            # Create message
            message = {
                "text": text,
                "try_trigger_generation": True
            }
            
            # Send to WebSocket
            await self.ws.send_json(message)
            return True
            
        except Exception as e:
            logger.error(f"Error sending text to ElevenLabs: {str(e)}")
            self.is_connected = False
            return False
    
    async def stream_end(self):
        """Signal end of stream with empty text"""
        if not self.is_connected:
            return False
            
        try:
            # Check if websocket is still open before sending
            if self.ws and not self.ws.closed:
                # Send empty message to signal end
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
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
            self.ws = None
            
        # Close session
        if self.session:
            try:
                await self.session.close()
            except:
                pass
            self.session = None
    
    async def close(self):
        """Close the WebSocket connection"""
        self.is_closed = True
        
        # Send end signal if possible
        if self.is_connected and self.ws and not self.ws.closed:
            try:
                await self.stream_end()
                # Brief delay to allow processing
                await asyncio.sleep(0.5)
            except:
                pass
                
        # Clean up resources
        await self._cleanup()
        logger.info("Closed ElevenLabs WebSocket connection")
        
    async def get_audio(self, timeout=5.0):
        """Get next audio chunk from queue with timeout"""
        try:
            return await asyncio.wait_for(self.audio_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
            
    async def get_all_audio(self):
        """Get all available audio in queue"""
        chunks = []
        while not self.audio_queue.empty():
            chunks.append(await self.audio_queue.get())
        return b''.join(chunks)