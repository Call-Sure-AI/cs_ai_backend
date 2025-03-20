# Add this class to tts_service.py

import aiohttp
import asyncio
import base64
import logging
import json
import time
import os
from typing import Optional, AsyncGenerator, Dict, Any, Callable

logger = logging.getLogger(__name__)

class WebSocketTTSService:
    def __init__(self):
        """Initialize WebSocket-based ElevenLabs TTS Service"""
        self.voice_id = os.getenv("VOICE_ID", "IKne3meq5aSn9XLyUdCD")
        self.api_key = os.getenv("ELEVEN_LABS_API_KEY")
        self.base_url = "wss://api.elevenlabs.io/v1/text-to-speech"
        self.ws = None
        self.audio_callback = None
        self.is_ready = False
        self.pending_audio = []
        self.session = None
        
        # Validate configuration
        if not self.api_key:
            logger.warning("ElevenLabs API key is not set. TTS services will not work.")
    
    async def connect(self, audio_callback: Callable[[bytes], Any] = None):
        """
        Connect to ElevenLabs WebSocket API
        
        Args:
            audio_callback: Optional callback to receive audio chunks as they arrive
        """
        if self.ws is not None:
            await self.close()
            
        self.audio_callback = audio_callback
        self.is_ready = False
        self.pending_audio = []
        
        try:
            # Construct WS URL with parameters
            url = f"{self.base_url}/{self.voice_id}/stream-input"
            params = {
                "model_id": "eleven_turbo_v2_5",  # Using turbo for faster generation
                "output_format": "mulaw_8000",  # Direct Twilio-compatible format
                "optimize_streaming_latency": "3",  # Max optimization
                "auto_mode": "false",  # We'll handle chunking for better quality
            }
            
            # Add query params to URL
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{url}?{query_string}"
            
            logger.info(f"Connecting to ElevenLabs WebSocket at {full_url}")
            
            # Connect to WebSocket
            self.session = aiohttp.ClientSession()
            headers = {"xi-api-key": self.api_key}
            self.ws = await self.session.ws_connect(full_url, headers=headers)
            
            # Start listening for audio chunks
            asyncio.create_task(self._listen_for_audio())
            
            # Initialize connection with empty text
            voice_settings = {
                "stability": 0.3,  # Lower for faster response
                "similarity_boost": 0.5,  # Lower for faster response
                "speed": 1.2  # Slightly faster speech
            }
            
            init_message = {
                "text": " ",
                "voice_settings": voice_settings
            }
            
            await self.ws.send_json(init_message)
            self.is_ready = True
            logger.info("Connected to ElevenLabs WebSocket API")
            
            return True
        
        except Exception as e:
            logger.error(f"Error connecting to ElevenLabs WebSocket: {str(e)}")
            return False
    
    async def _listen_for_audio(self):
        """Listen for audio chunks from ElevenLabs"""
        if self.ws is None:
            return
            
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    # Check if this is an audio chunk
                    if "audio" in data:
                        # Decode base64 audio
                        audio_bytes = base64.b64decode(data["audio"])
                        
                        # If we have a callback, send the audio
                        if self.audio_callback:
                            await self.audio_callback(audio_bytes)
                        else:
                            # Store for later retrieval
                            self.pending_audio.append(audio_bytes)
                            
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in WebSocket audio listener: {str(e)}")
        finally:
            logger.info("WebSocket audio listener stopped")
    
    async def stream_text(self, text: str, trigger_gen: bool = True):
        """
        Stream text to ElevenLabs for TTS generation
        
        Args:
            text: Text chunk to send
            trigger_gen: Whether to trigger generation (True for most chunks)
        """
        if not self.is_ready or self.ws is None:
            logger.warning("WebSocket not connected, attempting to reconnect")
            success = await self.connect(self.audio_callback)
            if not success:
                logger.error("Failed to reconnect to ElevenLabs")
                return False
        
        try:
            message = {
                "text": text,
                "try_trigger_generation": trigger_gen
            }
            
            await self.ws.send_json(message)
            return True
            
        except Exception as e:
            logger.error(f"Error sending text to ElevenLabs: {str(e)}")
            return False
    
    async def close(self):
        """Close the WebSocket connection"""
        if self.ws is not None:
            try:
                # Send empty text to signal end
                end_message = {"text": ""}
                await self.ws.send_json(end_message)
                await self.ws.close()
            except:
                pass
            finally:
                self.ws = None
                self.is_ready = False
                if self.session:
                    await self.session.close()
                    self.session = None
                logger.info("Closed ElevenLabs WebSocket connection")
    
    async def get_pending_audio(self):
        """Get and clear pending audio chunks"""
        audio = b''.join(self.pending_audio)
        self.pending_audio = []
        return audio