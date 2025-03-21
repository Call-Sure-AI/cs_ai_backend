# services/speech/deepgram_speech_service.py

import logging
import asyncio
from typing import Dict, Optional, Callable, Awaitable, Any
import base64
import os
import json
import time
from deepgram import Deepgram

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveTranscriptionEvents
)

logger = logging.getLogger(__name__)

class DeepgramSpeechService:
    """Service to handle speech-to-text conversion for Twilio calls using Deepgram"""
    
    def __init__(self):
        """Initialize the DeepgramSpeechService"""
        self.active_sessions: Dict[str, Dict] = {}
        
        # Get Deepgram API key from environment variable
        self.deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not self.deepgram_api_key:
            logger.warning("DEEPGRAM_API_KEY environment variable not set - speech recognition will fail")
            
        # Store connection objects for each session
        self.dg_connections = {}
        self.transcript_parts = {}
            
    async def initialize_session(self, session_id: str, 
                        transcript_callback: Optional[Callable[[str, str], Awaitable[Any]]] = None):
        """Initialize a new speech recognition session with Deepgram"""
        try:
            # Configure Deepgram client options with keepalive
            config = DeepgramClientOptions(
                options={"keepalive": "true"}
            )
            
            # Initialize Deepgram client with the config
            dg_client = DeepgramClient(self.deepgram_api_key, config)
            
            # Create transcript parts list for this session
            self.transcript_parts[session_id] = []
            
            # Create the live transcription connection
            # Updated: Use live.listen for latest SDK
            dg_connection = dg_client.listen.live.v("1")
            
            # Define event handlers
            async def on_message(result, **kwargs):
                """Handle incoming transcripts from Deepgram"""
                try:
                    if not result.channel or not result.channel.alternatives:
                        return
                        
                    sentence = result.channel.alternatives[0].transcript
                    if len(sentence.strip()) == 0:
                        return
                        
                    if result.is_final:
                        # This is a final transcript segment
                        self.transcript_parts[session_id].append(sentence)
                        
                        # If speech_final is True, the user has finished speaking
                        if result.speech_final:
                            full_transcript = ' '.join(self.transcript_parts[session_id])
                            self.transcript_parts[session_id] = []
                            logger.info(f"Final transcript for {session_id}: '{full_transcript}'")
                            
                            if transcript_callback:
                                await transcript_callback(session_id, full_transcript)
                    
                except Exception as e:
                    logger.error(f"Error processing Deepgram transcript: {str(e)}")
                    
            async def on_error(error, **kwargs):
                """Handle errors from Deepgram"""
                logger.error(f"Deepgram error for {session_id}: {error}")
                
            # Register event handlers
            dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
            dg_connection.on(LiveTranscriptionEvents.Error, on_error)
            
            # Set up connection options
            options = LiveOptions(
                model="nova-3", 
                language="en-US",
                smart_format=True,
                interim_results=True,
                utterance_end_ms="500",
                encoding="mulaw",
                channels=1,
                sample_rate=8000
            )
            
            # Start the connection - updated to handle async properly
            connection_successful = await dg_connection.start(options)
            
            if not connection_successful:
                logger.error(f"Failed to connect to Deepgram for session {session_id}")
                return False
                
            # Store the connection for this session
            self.dg_connections[session_id] = dg_connection
            logger.info(f"Deepgram session initialized for {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing Deepgram session for {session_id}: {str(e)}")
            return False
    
      
    async def process_audio_chunk(self, session_id: str, audio_data: bytes):
        """Process an audio chunk using Deepgram's live streaming API"""
        try:
            if session_id not in self.dg_connections:
                logger.error(f"No active Deepgram connection for session {session_id}")
                return False
                
            # Send the audio chunk to Deepgram
            dg_connection = self.dg_connections[session_id]
            await dg_connection.send(audio_data)
            return True
            
        except Exception as e:
            logger.error(f"Error processing audio chunk for {session_id}: {str(e)}")
            return False
    
    async def convert_twilio_audio(self, base64_payload: str, session_id: str) -> Optional[bytes]:
        """Convert Twilio's base64 audio format to raw bytes"""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(base64_payload)
            
            # Calculate audio energy for logging purposes
            silence_level = 128  # μ-law silence reference
            non_silent_bytes = [abs(b - silence_level) for b in audio_data]
            
            # Detect active audio
            threshold = 10  # Adjust this value to fine-tune silence detection
            active_bytes = sum(1 for b in non_silent_bytes if b > threshold)
            
            # Calculate metrics
            total_bytes = len(audio_data)
            silence_percentage = ((total_bytes - active_bytes) / total_bytes) * 100
            max_energy = max(non_silent_bytes) if non_silent_bytes else 0
            
            # Log audio characteristics
            logger.info(
                f"Audio Conversion Details for {session_id}: "
                f"Base64 Input: {len(base64_payload)} chars, "
                f"Raw Bytes: {total_bytes}, "
                f"Active Bytes: {active_bytes}, "
                f"Max Energy: {max_energy}, "
                f"Silence: {silence_percentage:.2f}%"
            )
            
            # For extremely silent audio (completely silent or almost silent),
            # it's better to skip processing to avoid errors and reduce unnecessary processing
            if active_bytes == 0 or max_energy <= threshold:
                logger.debug(f"Silent audio detected for {session_id}, skipping")
                return None
                
            return audio_data
            
        except Exception as e:
            logger.error(f"Audio conversion error for {session_id}: {str(e)}")
            return None
    
    async def close_session(self, session_id: str):
        """Close a speech recognition session"""
        if session_id in self.dg_connections:
            try:
                # Finish the Deepgram connection
                await self.dg_connections[session_id].finish()
                
                # Remove the session
                del self.dg_connections[session_id]
                
                # Clean up transcript parts
                if session_id in self.transcript_parts:
                    del self.transcript_parts[session_id]
                    
                logger.info(f"Closed Deepgram session for {session_id}")
                return True
            except Exception as e:
                logger.error(f"Error closing Deepgram session for {session_id}: {str(e)}")
                return False
                
        return False