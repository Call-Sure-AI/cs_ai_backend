

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
    logger.info(f"Received incoming call from {request.client.host}")

    try:
        form_data = await request.form()
        logger.info(f"Form data: {dict(form_data)}")

        # Extract call details
        call_sid = form_data.get("CallSid", "unknown_call")
        caller = form_data.get("From", "unknown")

        # Generate a unique WebRTC peer ID
        peer_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"Generated peer_id: {peer_id}")

        # Store call information
        active_calls[call_sid] = {
            "peer_id": peer_id,
            "caller": caller,
            "start_time": form_data.get("Timestamp"),
            "status": "initiated",
            "last_activity": time.time(),
        }

        # Get WebRTC signaling URL
        host = request.headers.get("host") or request.base_url.hostname
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"

        stream_url = f"wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}"
        logger.info(f"Setting up stream URL: {stream_url}")

        # Create TwiML response
        resp = VoiceResponse()

        # WebRTC media streaming
        start = Start()
        start.stream(url=stream_url, track="both")
        resp.append(start)

        # Initial greeting (actual AI response will come via WebRTC)
        resp.say("Hello, I am your AI assistant. How can I help you today?", voice="Polly.Matthew")

        # Gather input (keeps Twilio call active while WebRTC streams responses)
        resp.gather(input="speech", timeout=20, action="/api/v1/twilio/gather")

        return Response(content=resp.to_xml(), media_type="application/xml")

    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}", exc_info=True)
        return Response(
            content=VoiceResponse().say("An error occurred. Please try again later.", voice="alice").to_xml(),
            media_type="application/xml",
        )

@router.post("/gather")
async def handle_gather(
    request: Request,
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
):
    """Handles speech recognition results from Twilio Gather verb."""
    try:
        logger.info(f"Received Twilio Gather request - CallSid: {CallSid}, SpeechResult: {SpeechResult}")

        # Ensure manager is initialized
        manager = request.app.state.connection_manager
        if manager is None:
            logger.error("Connection manager not initialized!")
            return Response(content="<Response><Say>System error occurred.</Say></Response>", media_type="application/xml")

        # Retrieve WebRTC peer ID
        if CallSid not in active_calls:
            logger.warning(f"CallSid {CallSid} not found.")
            return Response(content="<Response><Say>Call session not found.</Say></Response>", media_type="application/xml")

        client_id = active_calls[CallSid]["peer_id"]

        # Log message being sent to WebRTC
        message_data = {"type": "message", "message": SpeechResult, "source": "twilio"}
        logger.info(f"Sending message to WebRTC client {client_id}: {message_data}")

        # Send recognized speech to WebRTC (WebRTC handles AI processing)
        await manager.process_streaming_message(client_id, message_data)

        response_xml = "<Response></Response>"
        logger.info(f"Response sent to Twilio: {response_xml}")
        return Response(content=response_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Error in gather handler: {str(e)}", exc_info=True)
        response_xml = "<Response><Say>I'm sorry, we encountered a technical issue.</Say></Response>"
        logger.info(f"Error Response sent to Twilio: {response_xml}")
        return Response(content=response_xml, media_type="application/xml")



@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")


@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")
