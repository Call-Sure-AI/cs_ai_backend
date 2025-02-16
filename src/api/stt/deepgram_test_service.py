import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("deepgram_test_service")

class DeepgramTestAgent:
    async def process_test_agent_audio(self, websocket: WebSocket):
        """Handles WebRTC test agent STT and AI processing."""
        await websocket.accept()

        try:
            while True:
                data = await websocket.receive_bytes()
                transcript = await self.deepgram_stt.process_audio_stream(data)
                ai_processed_text = await self.process_ai(transcript)
                await websocket.send_json({"transcript": transcript, "ai_response": ai_processed_text})

        except WebSocketDisconnect:
            logger.warning("Test agent disconnected.")
        except Exception as e:
            logger.error(f"Error processing test agent: {e}")
            await websocket.close()

    async def process_ai(self, text):
        """Placeholder for AI processing (e.g., intent detection)."""
        return f"AI processed: {text}"
