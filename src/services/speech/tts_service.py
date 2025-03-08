# services/speech/tts_service.py

import logging
import asyncio
from typing import Dict, Optional, List
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Say, Pause
from config.settings import settings

logger = logging.getLogger(__name__)

class TextToSpeechService:
    """Service to handle text-to-speech conversion for Twilio calls"""
    
    def __init__(self):
        self.twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.active_calls: Dict[str, Dict] = {}
        self.speech_queue: Dict[str, List[str]] = {}
        self.processing_queue: Dict[str, bool] = {}
        
    async def register_call(self, call_sid: str, caller_id: str):
        """Register a new call for TTS processing"""
        self.active_calls[call_sid] = {
            "caller_id": caller_id,
            "status": "connected",
            "last_activity": asyncio.get_event_loop().time()
        }
        self.speech_queue[call_sid] = []
        self.processing_queue[call_sid] = False
        logger.info(f"Registered call {call_sid} for TTS processing")
        
    def unregister_call(self, call_sid: str):
        """Remove a call from TTS processing"""
        if call_sid in self.active_calls:
            del self.active_calls[call_sid]
        
        if call_sid in self.speech_queue:
            del self.speech_queue[call_sid]
            
        if call_sid in self.processing_queue:
            del self.processing_queue[call_sid]
            
        logger.info(f"Unregistered call {call_sid} from TTS processing")
        
    async def queue_speech(self, call_sid: str, text: str):
        """Queue text to be converted to speech for a call"""
        if call_sid not in self.active_calls:
            logger.warning(f"Attempted to queue speech for unknown call: {call_sid}")
            return False
            
        # Add to queue
        if call_sid not in self.speech_queue:
            self.speech_queue[call_sid] = []
            
        self.speech_queue[call_sid].append(text)
        
        # Start processing queue if not already running
        if not self.processing_queue.get(call_sid, False):
            asyncio.create_task(self.process_speech_queue(call_sid))
            
        return True
        
    async def process_speech_queue(self, call_sid: str):
        """Process queued speech for a call"""
        if call_sid not in self.speech_queue or call_sid not in self.active_calls:
            return
            
        # Mark as processing
        self.processing_queue[call_sid] = True
        
        try:
            while self.speech_queue[call_sid]:
                # Only process if call is still active
                if self.active_calls.get(call_sid, {}).get("status") != "connected":
                    break
                    
                # Get next text chunk
                text = self.speech_queue[call_sid].pop(0)
                
                # Update last activity time
                self.active_calls[call_sid]["last_activity"] = asyncio.get_event_loop().time()
                
                # Send to Twilio
                await self.send_speech_to_twilio(call_sid, text)
                
                # Small delay to avoid overwhelming the call
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error processing speech queue for call {call_sid}: {str(e)}")
            
        finally:
            # Mark as not processing
            self.processing_queue[call_sid] = False
            
    async def send_speech_to_twilio(self, call_sid: str, text: str):
        """Send text as speech to an active Twilio call"""
        try:
            # Clean up text for TwiML
            cleaned_text = text.replace("&", "and").replace("<", "").replace(">", "")
            
            # Create TwiML for speech
            response = VoiceResponse()
            response.say(cleaned_text, voice="alice")
            
            # Send to Twilio
            self.twilio_client.calls(call_sid).update(
                twiml=str(response)
            )
            
            logger.info(f"Sent speech to call {call_sid}: {cleaned_text[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error sending speech to Twilio call {call_sid}: {str(e)}")
            return False