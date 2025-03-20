# services/speech/stt_service.py

import logging
import asyncio
from typing import Dict, Optional, Callable, Awaitable, Any
import io
import wave
import base64
import aiohttp
import os
import json
import time


logger = logging.getLogger(__name__)
class SpeechToTextService:
    """Service to handle speech-to-text conversion for Twilio calls using Deepgram"""
    
    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        
        # Get Deepgram API key from environment variable or use a default for development
        self.deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
        self.deepgram_url = "https://api.deepgram.com/v1/listen"
        if not self.deepgram_api_key:
            logger.warning("DEEPGRAM_API_KEY environment variable not set - speech recognition will fail")
            
    async def process_audio_chunk(self, session_id: str, audio_data: bytes, 
                                 callback: Optional[Callable[[str, str], Awaitable[Any]]] = None):
        """Process an audio chunk for a session"""
        try:
            if session_id not in self.active_sessions:
                # Initialize new session
                self.active_sessions[session_id] = {
                    "buffer": bytearray(),
                    "last_activity": time.time(),
                    "processing": False,
                    "chunk_count": 0,
                }
                
            # Add to buffer
            self.active_sessions[session_id]["buffer"].extend(audio_data)
            self.active_sessions[session_id]["chunk_count"] += 1
            self.active_sessions[session_id]["last_activity"] = time.time()
            
            # Check if we've accumulated enough data for transcription
            buffer_size = len(self.active_sessions[session_id]["buffer"])
            
            # Log buffer growth occasionally
            if self.active_sessions[session_id]["chunk_count"] % 100 == 0:
                logger.info(f"Audio buffer for {session_id}: {buffer_size} bytes after {self.active_sessions[session_id]['chunk_count']} chunks")
            
            # Only process if buffer has meaningful data and not already processing
            # For Twilio mulaw 8kHz audio, a good threshold is around 16000 bytes
            # (about 1 second of speech)
            if buffer_size > 16000 and not self.active_sessions[session_id]["processing"]:
                self.active_sessions[session_id]["processing"] = True
                
                # Get buffer copy
                audio_buffer = bytes(self.active_sessions[session_id]["buffer"])
                
                # Clear the buffer after copying
                self.active_sessions[session_id]["buffer"] = bytearray()
                
                # Process audio through Deepgram
                text = await self._recognize_speech(audio_buffer, session_id)
                
                # If text was recognized and callback provided
                if text and callback and text.strip():
                    logger.info(f"Recognized speech for {session_id}: '{text}'")
                    await callback(session_id, text)
                elif text and text.strip():
                    logger.info(f"Recognized speech for {session_id} but no callback: '{text}'")
                elif self.active_sessions[session_id]["chunk_count"] > 500:
                    # If we've collected a lot of audio but still no speech, log it
                    logger.warning(f"No speech detected after {self.active_sessions[session_id]['chunk_count']} chunks for {session_id}")
                    
                self.active_sessions[session_id]["processing"] = False
                
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio chunk for session {session_id}: {str(e)}")
            return False
            
    async def _recognize_speech(self, audio_data: bytes, session_id: str) -> Optional[str]:
        """Convert audio data to text using Deepgram"""
        try:
            # Deepgram API requires specific headers with Token format
            headers = {
                "Authorization": f"Token {self.deepgram_api_key}",
                "Content-Type": "audio/x-mulaw",
            }
            
            # Build the URL with proper query parameters for mulaw audio
            params = {
                "model": "nova-2",
                "sample_rate": "8000",
                "encoding": "mulaw",
                "channels": "1",
                "punctuate": "true",
                "smart_format": "true",
                "filler_words": "false",  # Ignore filler words like "um"
            }
            
            # Construct the URL properly
            from urllib.parse import urlencode
            query_string = urlencode(params)
            url = f"{self.deepgram_url}?{query_string}"
            
            # Log the request
            logger.info(f"Sending {len(audio_data)} bytes of audio to Deepgram for session {session_id}")
            
            # Make the API request to Deepgram
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    data=audio_data,
                    timeout=10  # 10 second timeout
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Deepgram API error: {response.status} - {error_text}")
                        return None
                        
                    # Parse the JSON response
                    result = await response.json()
                    
                    # Log the full response for debugging
                    logger.debug(f"Deepgram response: {json.dumps(result)}")
                    
                    # Extract the transcript from the response
                    if result and "results" in result and "channels" in result["results"]:
                        channel = result["results"]["channels"][0]
                        if "alternatives" in channel and len(channel["alternatives"]) > 0:
                            transcript = channel["alternatives"][0].get("transcript", "")
                            
                            if transcript:
                                logger.info(f"Deepgram recognized: '{transcript}' for session {session_id}")
                                return transcript
                            else:
                                logger.info(f"No speech detected for session {session_id}")
                                return None
            
            logger.warning(f"Could not extract transcript from Deepgram response for session {session_id}")
            return None
            
        except aiohttp.ClientError as e:
            logger.error(f"Deepgram API request error for session {session_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error recognizing speech for session {session_id}: {str(e)}", exc_info=True)
            return None
            
    def close_session(self, session_id: str):
        """Close a speech recognition session"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            logger.info(f"Closed speech recognition session {session_id}")
            return True
            
        return False
        
    async def process_final_buffer(self, session_id: str, 
                                  callback: Optional[Callable[[str, str], Awaitable[Any]]] = None):
        """Process any remaining audio in the buffer when a session ends"""
        if session_id not in self.active_sessions:
            return False
            
        try:
            # Only process if we have enough data and not already processing
            buffer_size = len(self.active_sessions[session_id]["buffer"])
            
            if buffer_size > 8000 and not self.active_sessions[session_id]["processing"]:
                # Minimum threshold of 8000 bytes (~0.5 second) to avoid processing noise
                self.active_sessions[session_id]["processing"] = True
                
                # Get buffer copy
                audio_buffer = bytes(self.active_sessions[session_id]["buffer"])
                
                # Clear the buffer
                self.active_sessions[session_id]["buffer"] = bytearray()
                
                # Process audio through Deepgram
                text = await self._recognize_speech(audio_buffer, session_id)
                
                # If text was recognized and callback provided
                if text and callback and text.strip():
                    logger.info(f"Final buffer recognized: '{text}' for session {session_id}")
                    await callback(session_id, text)
                    
                self.active_sessions[session_id]["processing"] = False
                
            return True
            
        except Exception as e:
            logger.error(f"Error processing final buffer for session {session_id}: {str(e)}")
            return False
            
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes"""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Only log occasionally to avoid log spam
            if self.active_sessions.get(session_id, {}).get("chunk_count", 0) % 100 == 0:
                logger.debug(f"Converted {len(base64_payload)} chars of base64 to {len(audio_data)} bytes for session {session_id}")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"Error converting Twilio audio for session {session_id}: {str(e)}")
            return None

    async def detect_silence(self, session_id: str, silence_threshold_sec: float = 2.0) -> bool:
        """Check if there has been silence (no new audio) for a specified duration"""
        if session_id not in self.active_sessions:
            return False
            
        current_time = time.time()
        last_activity = self.active_sessions[session_id]["last_activity"]
        
        return (current_time - last_activity) >= silence_threshold_sec
    
    def clear_buffer(self, session_id: str):
        """Clear the audio buffer for a specific session"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id]["buffer"] = bytearray()
            return True
        return False