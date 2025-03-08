import base64
from google.cloud import texttospeech
import logging

logger = logging.getLogger(__name__)

class TextToSpeechService:
    def __init__(self):
        self.client = texttospeech.TextToSpeechClient()

    async def generate_audio(self, text: str) -> bytes:
        """
        Convert text to speech using Google Cloud Text-to-Speech.

        Args:
            text (str): The text input to be converted to speech.

        Returns:
            bytes: The generated speech audio in bytes.
        """
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MULAW,
                sample_rate_hertz=8000  # Twilio expects 8kHz mu-law audio
            )

            response = self.client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            logger.info(f"Generated TTS audio for text: {text[:50]}...")
            return response.audio_content
        except Exception as e:
            logger.error(f"Error generating TTS audio: {str(e)}", exc_info=True)
            return b""  # Return empty bytes if failed
