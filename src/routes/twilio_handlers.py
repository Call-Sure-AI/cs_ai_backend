

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
    logger.info(f"[TWILIO_DEBUG] Received incoming call from {request.client.host}")

    try:
        # Extensive logging for incoming call
        logger.info(f"[TWILIO_CALL_INCOMING] Received call from IP: {request.client.host}")
        
        # Log full form data with sensitive information masked
        form_data = await request.form()
        masked_form_data = {
            key: (value if key not in ['CallSid', 'From', 'To'] else f"*{value[-4:]}")
            for key, value in dict(form_data).items()
        }
        logger.debug(f"[TWILIO_CALL_INCOMING] Form Data: {masked_form_data}")

        # Extract and log call details
        call_sid = form_data.get("CallSid", "unknown_call")
        caller = form_data.get("From", "unknown")
        called = form_data.get("To", "unknown")
        
        logger.info(f"[TWILIO_CALL_INCOMING] Call Details:")
        logger.info(f"  - Call SID: {call_sid}")
        logger.info(f"  - Caller: {caller}")
        logger.info(f"  - Called Number: {called}")

        # Generate unique WebRTC peer ID
        peer_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"[TWILIO_CALL_INCOMING] Generated Peer ID: {peer_id}")

        # Store call information
        global active_calls
        if not 'active_calls' in globals():
            active_calls = {}

        active_calls[call_sid] = {
            "peer_id": peer_id,
            "caller": caller,
            "start_time": form_data.get("Timestamp"),
            "status": "initiated",
            "last_activity": time.time(),
        }
        
        # Ensure client call mapping exists
        if not hasattr(request.app.state, 'client_call_mapping'):
            request.app.state.client_call_mapping = {}
        
        # Store mapping both ways
        request.app.state.client_call_mapping[peer_id] = call_sid

        # Construct WebRTC signaling URL
        host = request.headers.get("host") or request.base_url.hostname
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"

        stream_url = f"wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}"
        logger.info(f"[TWILIO_CALL_INCOMING] WebRTC Stream URL: {stream_url}")

        # Create TwiML response
        resp = VoiceResponse()

        # WebRTC media streaming
        start = Start()
        start.stream(url=stream_url, track="both")
        resp.append(start)

        # Initial greeting
        resp.say("Hello, I am your AI assistant. How can I help you today?", voice="Polly.Matthew")

        # Gather input
        resp.gather(input="speech", timeout=20, action="/api/v1/twilio/gather")
        
        # Log TwiML response
        resp_xml = resp.to_xml()
        logger.debug(f"[TWILIO_CALL_INCOMING] TwiML Response:\n{resp_xml}")


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
    """Enhanced logging for Twilio gather endpoint"""
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

        # Find client ID
        client_id = None
        client_call_mapping = getattr(request.app.state, 'client_call_mapping', {})
        logger.debug(f"[TWILIO_GATHER] Client Call Mapping: {client_call_mapping}")

        for cid, sid in client_call_mapping.items():
            if sid == CallSid:
                client_id = cid
                break
        
        if not client_id:
            logger.warning(f"[TWILIO_GATHER] No client ID found for CallSid: {CallSid}")
            return Response(
                content=VoiceResponse().say("Call session not found.").to_xml(),
                media_type="application/xml"
            )
        
        logger.info(f"[TWILIO_GATHER] Matched Client ID: {client_id}")

        # Initialize response
        resp = VoiceResponse()
        
        # Process new input if available
        if SpeechResult:
            message_data = {
                "type": "message", 
                "message": SpeechResult, 
                "source": "twilio"
            }
            logger.info(f"[TWILIO_GATHER] Sending message to WebRTC client {client_id}: {message_data}")

            # Trigger async processing
            active_connections = manager.active_connections
            logger.debug(f"[TWILIO_GATHER] Active Connections: {list(active_connections.keys())}")
            
            if client_id in active_connections:
                connection = active_connections[client_id]
                is_closed = manager.websocket_is_closed(connection)
                logger.debug(f"[TWILIO_GATHER] WebSocket for {client_id} closed: {is_closed}")
                
                if not is_closed:
                    asyncio.create_task(manager.process_streaming_message(client_id, message_data))
                else:
                    logger.warning(f"[TWILIO_GATHER] WebSocket closed for client {client_id}")
        
        # Retrieve cached response
        response_text = "I'm processing your request. Could you please repeat?"
        response_cache = getattr(request.app.state, 'response_cache', {})
        logger.debug(f"[TWILIO_GATHER] Response Cache Keys: {list(response_cache.keys())}")
        
        if client_id in response_cache:
            cached_response = response_cache[client_id]
            logger.debug(f"[TWILIO_GATHER] Cached Response: {cached_response}")
            
            response_text = cached_response.get("text", response_text)
            
            # Remove from cache
            del request.app.state.response_cache[client_id]
        
        # Add response to TwiML
        logger.info(f"[TWILIO_GATHER] Responding with: {response_text}")
        resp.say(response_text, voice="Polly.Matthew")
        
        # Continue gathering speech input
        resp.gather(input="speech", timeout="20", action="/api/v1/twilio/gather")
        
        # Log and return the response
        response_xml = resp.to_xml()
        logger.debug(f"[TWILIO_GATHER] TwiML Response:\n{response_xml}")
        
        return Response(content=response_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"[TWILIO_GATHER] Unexpected error: {str(e)}", exc_info=True)
        
        # Fallback error response
        resp = VoiceResponse()
        resp.say("I'm sorry, we encountered a technical issue.", voice="Polly.Matthew")
        return Response(content=resp.to_xml(), media_type="application/xml")

@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")


@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")
