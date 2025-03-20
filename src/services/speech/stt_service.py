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
        try:
            # Buffer audio chunks
            if session_id not in self.active_sessions:
                self.active_sessions[session_id] = {
                    "buffer": bytearray(),
                    "chunk_count": 0,
                    "last_activity": time.time()
                }
            
            session = self.active_sessions[session_id]
            session["buffer"].extend(audio_data)
            session["chunk_count"] += 1
            session["last_activity"] = time.time()
            
            # Combine audio chunks for more robust transcription
            MIN_BUFFER_SIZE = 2000  # Minimum bytes for transcription
            MAX_BUFFER_SIZE = 10000  # Maximum buffer size
            
            if len(session["buffer"]) >= MIN_BUFFER_SIZE and len(session["buffer"]) <= MAX_BUFFER_SIZE:
                # Attempt transcription of accumulated buffer
                text = await self._recognize_speech(bytes(session["buffer"]), session_id)
                
                if text and callback:
                    logger.info(f"Transcribed speech for {session_id}: '{text}'")
                    await callback(session_id, text)
                
                # Clear buffer after processing
                session["buffer"].clear()
            
            return True
        
        except Exception as e:
            logger.error(f"Error processing audio chunk for {session_id}: {str(e)}")
            return False
    
       
    async def _recognize_speech(self, audio_data: bytes, session_id: str) -> Optional[str]:
        """Convert audio data to text using Deepgram"""
        try:
            
            if len(audio_data) > 1000:
                # Save a sample of audio data to a file for analysis
                sample_filename = f"/tmp/audio_sample_{session_id}_{int(time.time())}.mulaw"
                try:
                    with open(sample_filename, "wb") as f:
                        f.write(audio_data[:min(10000, len(audio_data))])
                    logger.info(f"Saved audio sample to {sample_filename}")
                except Exception as e:
                    logger.error(f"Failed to save audio sample: {e}")
            
            # Deepgram API requires specific headers with Token format
            headers = {
                "Authorization": f"Token {self.deepgram_api_key}",
                "Content-Type": "audio/x-mulaw",
            }
            
            # Build the URL with proper query parameters for mulaw audio
            # params = {
            #     "model": "nova-3",
            #     "sample_rate": 8000,
            #     "encoding": "mulaw",  # Try this instead of "mulaw"
            #     "channels": 1,
            #     "punctuate": True,
            #     "smart_format": True,
            #     "filler_words": False,
            #     "endpointing": True
            # }
            
            # # Construct the URL properly
            # from urllib.parse import urlencode
            # query_string = urlencode(params)
            # url = f"{self.deepgram_url}?{query_string}"
            
            # # Log the request
            # logger.info(f"Sending {len(audio_data)} bytes of audio to Deepgram for session {session_id}")
            
            url = f"{self.deepgram_url}?model=nova-3&sample_rate=8000&encoding=mulaw&channels=1"
        
            # Log the request
            logger.info(f"Sending {len(audio_data)} bytes of audio to Deepgram URL: {url}")
        
            
            
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
                    logger.info(f"Deepgram full response: {json.dumps(result)}")
                    
                    if result and "results" in result:
                        # Check if results contains useful diagnostic info
                        if "warnings" in result:
                            logger.warning(f"Deepgram warnings: {result['warnings']}")
                    
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
            
            # Reduce threshold from 8000 to 4000 bytes for faster processing
            if buffer_size > 4000 and not self.active_sessions[session_id]["processing"]:
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
        """Convert Twilio's base64 audio format to raw bytes with enhanced logging and processing"""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Enhanced logging with audio characteristics
            total_non_silence_bytes = sum(1 for b in audio_data if abs(b - 128) > 10)
            silence_percentage = (len(audio_data) - total_non_silence_bytes) / len(audio_data) * 100
            
            logger.info(
                f"Audio Conversion Details for {session_id}: "
                f"Base64 Input: {len(base64_payload)} chars, "
                f"Raw Bytes: {len(audio_data)}, "
                f"Non-Silence Bytes: {total_non_silence_bytes}, "
                f"Silence: {silence_percentage:.2f}%"
            )
            
            # Return audio data only if it contains meaningful signal
            if total_non_silence_bytes > len(audio_data) * 0.1:  # At least 10% non-silence
                return audio_data
            
            return None
            
        except Exception as e:
            logger.error(f"Audio conversion error for {session_id}: {str(e)}")
            return None
    
    
    async def detect_silence(self, session_id: str, silence_threshold_sec: float = 0.8):
        """Check if there has been silence (no new audio) for a specified duration"""
        if session_id not in self.active_sessions:
            return False
            
        current_time = time.time()
        last_activity = self.active_sessions[session_id]["last_activity"]
        
        # Shorter silence threshold (was 2.0, now 0.8 seconds)
        return (current_time - last_activity) >= silence_threshold_sec
   
    def clear_buffer(self, session_id: str):
        """Clear the audio buffer for a specific session"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id]["buffer"] = bytearray()
            return True
        return False