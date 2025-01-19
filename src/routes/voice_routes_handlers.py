from fastapi import APIRouter, HTTPException
from models.schemas import TTSRequest, STTRequest

voice_router = APIRouter()

@voice_router.post("/tts")
async def text_to_speech(request: TTSRequest):
    try:
        return {"audio_url": "generated_audio.mp3"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@voice_router.post("/stt")
async def speech_to_text(request: STTRequest):
    try:
        return {"text": "transcribed text"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))