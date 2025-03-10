

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

        global active_calls
        if not 'active_calls' in globals():
            active_calls = {}

        # Store call information
        active_calls[call_sid] = {
            "peer_id": peer_id,
            "caller": caller,
            "start_time": form_data.get("Timestamp"),
            "status": "initiated",
            "last_activity": time.time(),
        }
        
        if not hasattr(request.app.state, 'client_call_mapping'):
            request.app.state.client_call_mapping = {}
            
        # Store mapping both ways for easy lookup
        request.app.state.client_call_mapping[peer_id] = call_sid

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

        # Get connection manager from app state
        manager = request.app.state.connection_manager
        if not manager:
            logger.error("Connection manager not available in app state!")
            return Response(
                content=VoiceResponse().say("System error occurred.").to_xml(),
                media_type="application/xml"
            )

        # Retrieve WebRTC peer ID
        global active_calls
        if not 'active_calls' in globals():
            active_calls = {}
            
        if CallSid not in active_calls:
            logger.warning(f"CallSid {CallSid} not found in active_calls.")
            
            # Try to find in app state as fallback
            if hasattr(request.app.state, 'client_call_mapping'):
                # Find the client_id by reversing the mapping
                client_id = None
                for cid, sid in request.app.state.client_call_mapping.items():
                    if sid == CallSid:
                        client_id = cid
                        break
                        
                if not client_id:
                    return Response(
                        content=VoiceResponse().say("Call session not found.").to_xml(),
                        media_type="application/xml"
                    )
            else:
                return Response(
                    content=VoiceResponse().say("Call session not found.").to_xml(),
                    media_type="application/xml"
                )
        else:
            client_id = active_calls[CallSid]["peer_id"]
        
        # Initialize response
        resp = VoiceResponse()
        
        # First, check if we have a cached response for this client
        response_text = None
        if hasattr(request.app.state, 'response_cache') and client_id in request.app.state.response_cache:
            response_text = request.app.state.response_cache[client_id]["text"]
            logger.info(f"Found cached response for {client_id}: {response_text[:50]}...")
            
            # Remove from cache after using to avoid repetition
            del request.app.state.response_cache[client_id]
            
        # If we have a response, say it to the caller
        if response_text:
            resp.say(response_text, voice="Polly.Matthew")
        else:
            # Process the new input if we didn't find a stored response
            if SpeechResult:
                # Send for async processing (response won't be available for this return)
                message_data = {"type": "message", "message": SpeechResult, "source": "twilio"}
                logger.info(f"Sending message to WebRTC client {client_id}: {message_data}")

                # Try to process via WebRTC
                if client_id in manager.active_connections and not manager.websocket_is_closed(manager.active_connections[client_id]):
                    # Use create_task so we don't block this response
                    asyncio.create_task(manager.process_streaming_message(client_id, message_data))
                    resp.say("I'm processing your request...", voice="Polly.Matthew")
                else:
                    # Client disconnected, handle gracefully
                    resp.say("I'm sorry, our connection seems to have been lost. Please try your request again.", voice="Polly.Matthew")
            else:
                resp.say("I didn't catch that. Could you please repeat?", voice="Polly.Matthew")
        
        # Continue gathering speech input
        resp.gather(input="speech", timeout=20, action="/api/v1/twilio/gather")
        
        # Log and return the response
        response_xml = resp.to_xml()
        logger.info(f"Response sent to Twilio: {response_xml}")
        return Response(content=response_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Error in gather handler: {str(e)}", exc_info=True)
        resp = VoiceResponse()
        resp.say("I'm sorry, we encountered a technical issue.", voice="Polly.Matthew")
        return Response(content=resp.to_xml(), media_type="application/xml")


@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")


@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")
