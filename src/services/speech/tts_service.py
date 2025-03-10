import logging
import aiohttp
import base64
import asyncio
from typing import Optional
from config.settings import settings
import os

logger = logging.getLogger(__name__)

class TextToSpeechService:
    def __init__(self):
        """Initialize ElevenLabs TTS Service"""
        self.voice_id = os.getenv("VOICE_ID")
        self.api_key = os.getenv("ELEVEN_LABS_API_KEY")
        self.chunk_size = 32 * 1024  # 32KB per chunk for streaming
        self.chunk_delay = 0.01  # 10ms delay to prevent overloading
        
    async def generate_audio(self, text: str) -> Optional[bytes]:
        """
        Converts text to speech using ElevenLabs API.
        
        Args:
            text (str): The input text to be converted into speech.
        
        Returns:
            Optional[bytes]: The audio content in bytes or None if an error occurs.
        """
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key
            }

            payload = {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.8
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"ElevenLabs TTS API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error generating audio with ElevenLabs: {str(e)}")
            return None
    
    async def stream_text_to_speech(self, text: str):
        """
        Streams audio response from ElevenLabs API.

        Args:
            text (str): The input text to be converted into speech.
        
        Yields:
            bytes: Audio chunks as they arrive.
        """
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key
            }

            payload = {
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.8
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        async for chunk in response.content.iter_chunked(self.chunk_size):
                            yield chunk
                            await asyncio.sleep(self.chunk_delay)
                    else:
                        logger.error(f"ElevenLabs API streaming error: {response.status}")
        except Exception as e:
            logger.error(f"Error streaming audio from ElevenLabs: {str(e)}")
