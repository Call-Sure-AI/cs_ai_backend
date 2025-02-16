import asyncio
import websockets
import json
import os
import logging
from fastapi import WebSocket, WebSocketDisconnect
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
MAX_RETRIES = 3

logger = logging.getLogger("deepgram_service")
logging.basicConfig(level=logging.INFO)

class DeepgramSTT:
    def __init__(self, model="nova", language="en-US", encoding="opus", interim_results=True, filler_words=True, analyze_tone=True):
        self.api_key = DEEPGRAM_API_KEY
        self.model = model
        self.language = language
        self.encoding = encoding
        self.interim_results = interim_results
        self.filler_words = filler_words
        self.analyze_tone = analyze_tone

    async def process_audio_stream(self, websocket: WebSocket):
        """Handles real-time STT and analytics (urgency detection, tone, speech speed)."""
        await websocket.accept()
        headers = {"Authorization": f"Token {self.api_key}"}

        # Enable Deepgram's speech analytics
        params = (
            f"model={self.model}&language={self.language}&encoding={self.encoding}"
            f"&endpointing=true&interim_results={str(self.interim_results).lower()}"
            f"&filler_words={str(self.filler_words).lower()}"
            f"&detect_speech_speed=true"
            f"&analyze_sentiment={str(self.analyze_tone).lower()}"
            f"&diarize=true"
            f"&detect_silence=true"
            f"&detect_entities=true"
            f"&detect_confidence=true"
        )

        retries = 0
        while retries < MAX_RETRIES:
            try:
                async with websockets.connect(f"{DEEPGRAM_URL}?{params}", extra_headers=headers) as deepgram_ws:

                    async def send_audio():
                        """Sends audio and keeps connection alive."""
                        try:
                            while True:
                                audio_chunk = await websocket.receive_bytes()
                                if audio_chunk.strip():
                                    await deepgram_ws.send(audio_chunk)
                                else:
                                    await asyncio.sleep(0.5)
                                    await deepgram_ws.send(b"\x00" * 64)  # Keep-alive packet
                        except WebSocketDisconnect:
                            logger.warning("Client disconnected.")
                        except Exception as e:
                            logger.error(f"Error sending audio: {e}")

                    async def receive_transcriptions():
                        """Receives transcription + analytics from Deepgram."""
                        try:
                            async for message in deepgram_ws:
                                response = json.loads(message)

                                # Extract analytics
                                if "speech_final" in response:
                                    transcript = response["speech_final"]["transcript"]
                                    speech_speed = response["speech_final"].get("speech_speed", 0)
                                    sentiment = response["speech_final"].get("sentiment", "neutral")
                                    filler_word_count = response["speech_final"].get("filler_word_count", 0)
                                    silence_duration = response["speech_final"].get("silence_duration", 0)
                                    confidence_score = response["speech_final"].get("confidence", 1.0)

                                    # Determine urgency based on analytics
                                    urgency_level = self.detect_urgency(speech_speed, sentiment, filler_word_count, silence_duration)

                                    await websocket.send_json({
                                        "transcript": transcript,
                                        "speech_speed": speech_speed,
                                        "sentiment": sentiment,
                                        "filler_words": filler_word_count,
                                        "silence_duration": silence_duration,
                                        "confidence_score": confidence_score,
                                        "urgency_level": urgency_level
                                    })

                                elif "channel" in response:
                                    transcript = response["channel"]["alternatives"][0]["transcript"]
                                    if transcript:
                                        await websocket.send_json({"transcript": transcript})
                        except WebSocketDisconnect:
                            logger.warning("Client disconnected.")
                        except Exception as e:
                            logger.error(f"Error receiving transcription: {e}")

                    await asyncio.gather(send_audio(), receive_transcriptions())

                break  

            except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.WebSocketException) as e:
                retries += 1
                logger.error(f"WebSocket error: {e}. Retrying {retries}/{MAX_RETRIES}...")
                await asyncio.sleep(2 ** retries)

            except Exception as e:
                logger.critical(f"Unexpected error: {e}")
                break

        await websocket.close()
        logger.info("WebSocket connection closed.")

    def detect_urgency(self, speech_speed, sentiment, filler_words, silence_duration):
        """Determines urgency based on multiple speech parameters."""
        if speech_speed > 180 and sentiment in ["negative", "neutral"] and filler_words > 5:
            return "High Urgency"
        elif speech_speed > 140 and silence_duration < 1.5:
            return "Medium Urgency"
        else:
            return "Low Urgency"