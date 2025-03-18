

from fastapi import APIRouter, WebSocket, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Start
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

        # WebRTC media streaming
        start = Start()
        start.stream(url=stream_url, track="both")
        resp.append(start)
        
        # No <Say> element - we'll send audio via WebSocket

        # Gather input
        resp.gather(input="speech", timeout=20, action="/api/v1/twilio/gather")
        
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


   
@router.post("/gather")
async def handle_gather(
    request: Request,
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
):
    """Enhanced handler for Twilio gather endpoint that relies on WebSocket audio"""
    try:
        # Log gather request details
        logger.info(f"[TWILIO_GATHER] Received Gather Request")
        logger.debug(f"[TWILIO_GATHER] Call SID: {CallSid}")
        logger.debug(f"[TWILIO_GATHER] Speech Result: {SpeechResult}")

        # Get connection manager
        manager = request.app.state.connection_manager
        if not manager:
            logger.error("[TWILIO_GATHER] Connection manager not available!")
            return Response(
                content=VoiceResponse().say("System error occurred.").to_xml(),
                media_type="application/xml"
            )

        # Find client ID by looking up the call SID in our mapping
        client_id = None
        client_call_mapping = getattr(request.app.state, 'client_call_mapping', {})
        logger.debug(f"[TWILIO_GATHER] Available clients in mapping: {list(client_call_mapping.keys())}")
        
        for cid, sid in client_call_mapping.items():
            if sid == CallSid:
                client_id = cid
                break
        
        if not client_id:
            logger.warning(f"[TWILIO_GATHER] No client ID found for CallSid: {CallSid}")
            # Fallback to empty TwiML response with gather
            resp = VoiceResponse()
            resp.gather(input="speech", timeout="20", action="/api/v1/twilio/gather")
            return Response(content=resp.to_xml(), media_type="application/xml")
        
        logger.info(f"[TWILIO_GATHER] Matched Client ID: {client_id}")

        # Check if WebSocket is still active
        active_connections = manager.active_connections
        logger.debug(f"[TWILIO_GATHER] Active connections: {list(active_connections.keys())}")
        
        websocket_active = client_id in active_connections and not manager.websocket_is_closed(active_connections[client_id])
        logger.info(f"[TWILIO_GATHER] WebSocket active for {client_id}: {websocket_active}")
        
        # Process new input if available
        if SpeechResult and websocket_active:
            message_data = {
                "type": "message", 
                "message": SpeechResult, 
                "source": "twilio"
            }
            logger.info(f"[TWILIO_GATHER] Sending message to WebRTC client {client_id}: {message_data}")
            
            # Send the message to be processed by the AI and then sent over WebSocket
            # Create a new task to process this message asynchronously
            asyncio.create_task(manager.process_streaming_message(client_id, message_data))
            logger.info(f"[TWILIO_GATHER] Created async task to process message for {client_id}")

        # Create TwiML response WITHOUT a Say verb
        # This is the key fix - we're not using Twilio's voice at all
        # Instead we rely on the audio sent over WebSocket
        resp = VoiceResponse()
        
        # Check agent resources to determine if we should use specific TwiML
        agent_resources = manager.agent_resources.get(client_id, {})
        logger.info(f"[TWILIO_GATHER] Agent resources for {client_id} are {agent_resources}")
        
        # Get company info for additional context
        company_info = manager.client_companies.get(client_id, {})
        logger.info(f"[TWILIO_GATHER] Company info for {client_id} is {company_info}")
        
        # Continue gathering speech input
        # Use a shorter timeout to improve responsiveness
        resp.gather(input="speech", timeout="15", action="/api/v1/twilio/gather")
        
        # Log and return the response
        response_xml = resp.to_xml()
        logger.debug(f"[TWILIO_GATHER] TwiML Response:\n{response_xml}")
        
        return Response(content=response_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"[TWILIO_GATHER] Unexpected error: {str(e)}", exc_info=True)
        
        # Fallback error response
        resp = VoiceResponse()
        # Only use say for critical error fallbacks
        resp.say("I'm sorry, we encountered a technical issue. Please try again later.", voice="Polly.Matthew")
        resp.gather(input="speech", timeout="10", action="/api/v1/twilio/gather")
        return Response(content=resp.to_xml(), media_type="application/xml")


@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")


@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")



@router.get("/test-welcome")
async def test_welcome(request: Request):
    """
    Test route for Twilio: returns a TwiML response that instructs Twilio
    to play a welcome message generated by our TTS service.
    """
    # Get the host from the request headers (ensure this is publicly accessible)
    host = request.headers.get("host")
    # Construct the URL to the audio endpoint
    audio_url = f"https://{host}/api/v1/twilio/audio/welcome"
    logger.info(f"[TEST_WELCOME] Using audio URL: {audio_url}")

    # Create a TwiML response using <Play>
    resp = VoiceResponse()
    resp.play(url=audio_url)

    # Return the TwiML as XML
    return Response(content=resp.to_xml(), media_type="application/xml")


@router.get("/audio/welcome")
async def audio_welcome():
    """
    Generate the welcome audio using ElevenLabs TTS service,
    convert it to Twilio-compatible μ-law (8000 Hz, mono) audio,
    and return the audio data.
    """
    from services.speech.tts_service import TextToSpeechService

    tts_service = TextToSpeechService()
    welcome_text = "Hello! Welcome to Callsue AI. How may I help you today?"
    logger.info("[AUDIO_WELCOME] Generating welcome message audio.")

    # Generate MP3 audio from ElevenLabs TTS API (by default returns MP3)
    audio_bytes = await tts_service.generate_audio(welcome_text)
    if not audio_bytes:
        logger.error("[AUDIO_WELCOME] Error generating audio from TTS service.")
        return Response(content="Error generating audio", status_code=500)

    # Convert the MP3 audio to Twilio-compatible μ-law audio
    converted_audio = await tts_service.convert_audio_for_twilio(audio_bytes)
    if not converted_audio:
        logger.error("[AUDIO_WELCOME] Error converting audio to μ-law format.")
        return Response(content="Error converting audio", status_code=500)

    logger.info(f"[AUDIO_WELCOME] Successfully generated and converted audio ({len(converted_audio)} bytes).")
    return Response(content=converted_audio, media_type="audio/mulaw")