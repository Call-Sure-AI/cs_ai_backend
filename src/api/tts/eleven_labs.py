from fastapi import APIRouter, WebSocket, HTTPException
from src.services.audio.audio_service import AudioService
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
audio_service = AudioService()

@router.post("/text-to-speech")
async def text_to_speech(text: str, voice_settings: Optional[Dict] = None):
    """Convert text to speech using ElevenLabs API"""
    try:
        audio_content = await audio_service.text_to_speech(text, voice_settings)
        if not audio_content:
            raise HTTPException(status_code=500, detail="Failed to generate audio")
        return {"audio": audio_content}
    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for streaming text-to-speech"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text")
            voice_settings = data.get("voice_settings")
            
            if not text:
                continue
                
            async for chunk in audio_service.stream_text_to_speech(text, voice_settings):
                await websocket.send_bytes(chunk)
                
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await audio_service.handle_streaming_error(
            websocket, 
            e, 
            {"endpoint": "stream"}
        )