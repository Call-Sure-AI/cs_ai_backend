

from fastapi import APIRouter, WebSocket, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Start, Connect
import base64
from twilio.rest import Client
from typing import Optional, Dict, Any
import logging
import json
import uuid
from managers.connection_manager import ConnectionManager
from config.settings import settings
from routes.webrtc_handlers import router as webrtc_router
import time
import asyncio



router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize Twilio client
try:
    twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    logger.info("Twilio client initialized successfully")
except Exception as e:
    logger.critical(f"Failed to initialize Twilio client: {str(e)}")
    raise

manager: Optional[ConnectionManager] = None

# In-memory storage to track active calls (in production, use Redis or a database)
active_calls: Dict[str, Dict[str, Any]] = {}


@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handles incoming Twilio voice calls with WebRTC integration."""
    logger.info(f"[TWILIO_CALL_SETUP] Received incoming call from {request.client.host}")

    try:
        # Extract form data
        form_data = await request.form()
        call_sid = form_data.get("CallSid", "unknown_call")
        caller = form_data.get("From", "unknown")
        
        logger.info(f"[TWILIO_CALL_SETUP] Call SID: {call_sid}, Caller: {caller}")

        # Generate unique WebRTC peer ID
        peer_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"[TWILIO_CALL_SETUP] Generated Peer ID: {peer_id}")

        # Store call mapping
        if not hasattr(request.app.state, 'client_call_mapping'):
            request.app.state.client_call_mapping = {}
        request.app.state.client_call_mapping[peer_id] = call_sid

        # Construct WebRTC signaling URL
        host = request.headers.get("host") or request.base_url.hostname
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"

        stream_url = f"wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}"
        logger.info(f"[TWILIO_CALL_SETUP] WebRTC Stream URL: {stream_url}")

        # Create TwiML response - NO SAY ELEMENT AT ALL
        resp = VoiceResponse()

        connect = Connect()
        connect.stream(url=stream_url)
        resp.append(connect)
        
        
        # Log and return the TwiML
        resp_xml = resp.to_xml()
        logger.info(f"[TWILIO_CALL_SETUP] TwiML Response: {resp_xml}")
        
        return Response(content=resp.to_xml(), media_type="application/xml")

    except Exception as e:
        logger.error(f"[TWILIO_CALL_SETUP] Error: {str(e)}", exc_info=True)
        return Response(
            content=VoiceResponse().say("An error occurred. Please try again later.").to_xml(),
            media_type="application/xml",
        )




@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")


@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")



@router.get("/test-welcome-websocket")
def test_welcome_websocket(request: Request):
    """
    Returns TwiML that instructs Twilio to connect the call audio
    to a WebSocket endpoint. We'll send TTS audio from that endpoint.
    """
    host = request.headers.get("host") or "example.com"  # Replace with your domain
    ws_url = f"wss://{host}/api/v1/twilio/test-websocket"
    logger.info(f"[TEST_WELCOME_WEBSOCKET] Using WebSocket URL: {ws_url}")

    # Build a TwiML response
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=ws_url)
    response.append(connect)
    xml_response = response.to_xml()
    logger.debug(f"[TEST_WELCOME_WEBSOCKET] TwiML Response:\n{xml_response}")
    return Response(content=xml_response, media_type="application/xml")

@router.websocket("/test-websocket")
async def test_websocket(websocket: WebSocket):
    """
    WebSocket endpoint that Twilio connects to. 
    On 'start' event, we generate TTS, convert to μ-law, and send it as a single chunk.
    """
    await websocket.accept()
    logger.info("[TEST_WEBSOCKET] Twilio connected.")

    from services.speech.tts_service import TextToSpeechService

    connected = False
    stream_sid = None

    try:
        while True:
            # Wait for messages from Twilio
            message = await websocket.receive_text()
            data = json.loads(message)

            event_type = data.get("event")
            logger.debug(f"[TEST_WEBSOCKET] Received event: {event_type}")

            if event_type == "connected":
                connected = True

            elif event_type == "start":
                # Twilio provides the streamSid here
                start_info = data.get("start", {})
                stream_sid = start_info.get("streamSid")
                logger.info(f"[TEST_WEBSOCKET] Stream started with SID: {stream_sid}")

                # Generate TTS
                tts_service = TextToSpeechService()
                welcome_text = "Hello! This is a single-chunk welcome message over the WebSocket."
                mp3_bytes = await tts_service.generate_audio(welcome_text)

                if mp3_bytes:
                    # Convert MP3 to μ-law 8000 Hz
                    mu_law_audio = await tts_service.convert_audio_for_twilio(mp3_bytes)
                    if mu_law_audio:
                        # Base64-encode and send as 'media' event
                        encoded_audio = base64.b64encode(mu_law_audio).decode("utf-8")
                        media_message = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": encoded_audio}
                        }
                        await websocket.send_text(json.dumps(media_message))
                        logger.info("[TEST_WEBSOCKET] Sent single-chunk TTS audio.")

                        # Optionally send a 'mark' event to track playback
                        mark_message = {
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": "test-welcome-mark"}
                        }
                        await websocket.send_text(json.dumps(mark_message))
                        logger.info("[TEST_WEBSOCKET] Sent mark event.")
                    else:
                        logger.error("[TEST_WEBSOCKET] Error converting MP3 to mu-law.")
                else:
                    logger.error("[TEST_WEBSOCKET] Error generating TTS audio.")

            elif event_type == "stop":
                logger.info("[TEST_WEBSOCKET] Received 'stop' event from Twilio. Ending stream.")
                break

            # (You could handle 'media' from Twilio if you need inbound audio, etc.)

    except WebSocketDisconnect:
        logger.warning("[TEST_WEBSOCKET] WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[TEST_WEBSOCKET] Error: {e}", exc_info=True)
    finally:
        await websocket.close()
        logger.info("[TEST_WEBSOCKET] Connection closed.")