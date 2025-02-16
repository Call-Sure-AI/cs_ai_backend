import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from models.schemas import TTSRequest, STTRequest
from src.api.stt.deepgram_service import DeepgramSTT
from src.api.stt.deepgram_test_service import DeepgramTestAgent
from src.utils.s3_helper import upload_to_s3
import os

voice_router = APIRouter()
deepgram_stt = DeepgramSTT()
test_agent = DeepgramTestAgent(deepgram_stt)
logger = logging.getLogger("voice_routes")

# Directory to temporarily store audio before S3 upload
RECORDINGS_DIR = "recordings"

# -----------------------------------
# ✅ TEXT TO SPEECH (TTS)
# -----------------------------------
@voice_router.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Converts text to speech (Placeholder)."""
    try:
        return {"audio_url": "generated_audio.mp3"}
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------
# ✅ SPEECH TO TEXT (STT)
# -----------------------------------
@voice_router.post("/stt")
async def speech_to_text(request: STTRequest):
    """Converts speech to text (Placeholder)."""
    try:
        return {"text": "transcribed text"}
    except Exception as e:
        logger.error(f"STT Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------
# ✅ LIVE MOBILE CALL STT (WebSocket)
# -----------------------------------
@voice_router.websocket("/stt/deepgram/live")
async def deepgram_live_stt(websocket: WebSocket):
    """Handles real-time STT for mobile calls."""
    try:
        await deepgram_stt.process_audio_stream(websocket)
    except WebSocketDisconnect:
        logger.warning("Client disconnected from live STT session.")
    except Exception as e:
        logger.error(f"Live STT WebSocket Error: {e}")

# -----------------------------------
# ✅ WEBRTC TEST AGENT STT (WebSocket)
# -----------------------------------
@voice_router.websocket("/stt/deepgram/test")
async def deepgram_test_agent(websocket: WebSocket):
    """Handles real-time STT for WebRTC test agent."""
    try:
        await test_agent.process_test_agent_audio(websocket)
    except WebSocketDisconnect:
        logger.warning("Client disconnected from test agent STT session.")
    except Exception as e:
        logger.error(f"Test Agent WebSocket Error: {e}")

# -----------------------------------
# ✅ SAVE WEBRTC AUDIO & UPLOAD TO S3
# -----------------------------------
@voice_router.post("/save-recording")
async def save_recording(audio: UploadFile = File(...)):
    """
    Receives recorded WebRTC audio from Next.js frontend,
    temporarily saves it, uploads to S3, and deletes the local file.
    """
    try:
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        file_path = os.path.join(RECORDINGS_DIR, audio.filename)

        # Save file temporarily
        with open(file_path, "wb") as f:
            f.write(await audio.read())

        # Upload to S3
        s3_url = upload_to_s3(file_path, audio.filename)

        # Delete local file after upload
        os.remove(file_path)

        return {"message": "Recording saved", "s3_url": s3_url}

    except Exception as e:
        logger.error(f"Error saving recording: {e}")
        raise HTTPException(status_code=500, detail="Failed to save audio recording.")
