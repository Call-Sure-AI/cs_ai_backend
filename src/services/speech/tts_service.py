# In services/speech/tts_service.py

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
        """Connect to ElevenLabs WebSocket API with connection pooling"""
        async with self.connection_lock:
            # Reset state
            if self.is_connected:
                await self.close()
                
            self.audio_callback = audio_callback
            self.is_closed = False
            self.pool_key = f"{self.voice_id}"
            
            try:
                # Check if we have a pooled connection we can reuse
                async with self._pool_lock:
                    pool_entry = self._connection_pool.get(self.pool_key)
                    if pool_entry and not pool_entry['is_closed'] and time.time() - pool_entry['last_used'] < 60:
                        # Reuse existing connection if it's less than 60 seconds old
                        logger.info("Reusing existing ElevenLabs connection from pool")
                        self.session = pool_entry['session']
                        self.ws = pool_entry['ws']
                        pool_entry['last_used'] = time.time()
                        pool_entry['ref_count'] += 1
                        
                        # Start listener task for this instance
                        self.listener_task = asyncio.create_task(self._listen_for_audio())
                        self.is_connected = True
                        return True
                
                # If we get here, we need a new connection
                # Construct WebSocket URL with parameters
                url = f"{self.base_url}/{self.voice_id}/stream-input"
                params = {
                    "model_id": "eleven_turbo_v2",
                    "output_format": "pcm_44100",
                    "optimize_streaming_latency": "3",
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
                    heartbeat=30.0,
                    receive_timeout=60.0
                )
                
                # Start listener task
                self.listener_task = asyncio.create_task(self._listen_for_audio())
                
                # Initialize connection with empty text
                voice_settings = {
                    "stability": 0.3,
                    "similarity_boost": 0.5,
                    "speed": 1.0,
                }
                
                # Send initial message
                init_message = {
                    "text": " ",
                    "voice_settings": voice_settings
                }
                
                await self.ws.send_json(init_message)
                self.is_connected = True
                
                # Add to pool
                async with self._pool_lock:
                    self._connection_pool[self.pool_key] = {
                        'session': self.session,
                        'ws': self.ws,
                        'last_used': time.time(),
                        'is_closed': False,
                        'ref_count': 1
                    }
                
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
            audio_chunks_received = 0
            
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
                            audio_chunks_received += 1
                            
                            if audio_chunks_received == 1:
                                logger.info(f"Received first audio chunk from ElevenLabs: {len(audio_bytes)} bytes")
                            
                            # Convert PCM 44.1kHz to μ-law 8kHz for Twilio
                            mulaw_audio = self._convert_to_mulaw(audio_bytes)
                            
                            # Put in queue if callback isn't set
                            if self.audio_callback:
                                try:
                                    await self.audio_callback(mulaw_audio)
                                except Exception as e:
                                    logger.error(f"Error in audio callback: {str(e)}")
                            else:
                                await self.audio_queue.put(mulaw_audio)
                        # Log any error messages from ElevenLabs        
                        elif "error" in data:
                            logger.error(f"ElevenLabs API error: {data['error']}")
                        # Debug any other messages
                        else:
                            logger.info(f"ElevenLabs message: {data}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"Non-JSON response from ElevenLabs: {msg.data}")
                        
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("ElevenLabs WebSocket closed")
                    break
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"ElevenLabs WebSocket error: {msg.data}")
                    break
                    
            logger.info(f"ElevenLabs listener finished, received {audio_chunks_received} audio chunks")
            
        except asyncio.CancelledError:
            logger.info("ElevenLabs WebSocket listener task cancelled")
            
        except Exception as e:
            logger.error(f"Error in ElevenLabs WebSocket listener: {str(e)}")
            
        finally:
            logger.info("ElevenLabs WebSocket audio listener stopped")
    
    def _convert_to_mulaw(self, pcm_audio_bytes):
        """
        Convert PCM audio (44.1kHz, 16-bit, mono) to μ-law encoded audio (8kHz, 8-bit, mono)
        for Twilio compatibility
        """
        try:
            # Convert PCM audio to 8kHz sampling rate
            # First, assume the input is 16-bit PCM at 44.1kHz
            # Downsample from 44.1kHz to 8kHz
            downsampled_audio = audioop.ratecv(pcm_audio_bytes, 2, 1, 44100, 8000, None)[0]
            
            # Convert from 16-bit PCM to μ-law encoding (8-bit)
            mulaw_audio = audioop.lin2ulaw(downsampled_audio, 2)
            
            return mulaw_audio
            
        except Exception as e:
            logger.error(f"Error converting audio format: {str(e)}")
            # If conversion fails, return original audio as fallback
            return pcm_audio_bytes
            
    async def stream_text(self, text: str):
        """Stream text to ElevenLabs for TTS generation"""
        if not text or not text.strip():
            logger.debug("Empty text provided, skipping TTS generation")
            return True  # Consider empty text as success
            
        # Check connection state
        if not self.is_connected or not self.ws or self.ws.closed:
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
            
            # Send to WebSocket with timeout
            await asyncio.wait_for(self.ws.send_json(message), timeout=5.0)
            return True
            
        except asyncio.TimeoutError:
            logger.error("Timeout sending text to ElevenLabs")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Error sending text to ElevenLabs: {str(e)}")
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
        """Close the WebSocket connection with connection pooling"""
        if self.is_closed:
            return  # Already closed, avoid duplicate close
            
        self.is_closed = True
        
        # Try to send end signal
        try:
            if self.is_connected and self.ws and not self.ws.closed:
                await self.stream_end()
                await asyncio.sleep(0.2)  # Allow time for processing
        except Exception as e:
            logger.error(f"Error during stream end: {str(e)}")
        
        # Update pool reference count
        if self.pool_key:
            async with self._pool_lock:
                pool_entry = self._connection_pool.get(self.pool_key)
                if pool_entry:
                    pool_entry['ref_count'] -= 1
                    
                    # Only clean up if there are no more references
                    if pool_entry['ref_count'] <= 0:
                        pool_entry['is_closed'] = True
                        await self._cleanup()
                        # Remove from pool
                        self._connection_pool.pop(self.pool_key, None)
                    else:
                        # Other instances are still using this connection
                        logger.info(f"Keeping pooled connection for {self.pool_key}, ref count: {pool_entry['ref_count']}")
                        
                        # Just clean up our instance variables
                        self.ws = None
                        self.session = None
                        if self.listener_task and not self.listener_task.done():
                            self.listener_task.cancel()
                        self.listener_task = None
                        
                        logger.info("Released ElevenLabs WebSocket connection back to pool")
                        return
        else:
            # No pool key, just clean up
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