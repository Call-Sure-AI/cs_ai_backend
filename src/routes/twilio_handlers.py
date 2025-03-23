

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Start, Connect
import base64
from twilio.rest import Client
from twilio.request_validator import RequestValidator
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

# Define but don't initialize yet
twilio_client: Optional[Client] = None
twilio_validator: Optional[RequestValidator] = None
manager: Optional[ConnectionManager] = None

# In-memory storage to track active calls (in production, use Redis or a database)
active_calls: Dict[str, Dict[str, Any]] = {}

# Initialize Twilio client
@router.on_event("startup")
async def startup_event():
    global twilio_client, twilio_validator, manager
    
    try:
        # Check if we have the required settings
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            twilio_validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
            logger.info("Twilio client initialized successfully")
        else:
            logger.warning("Missing Twilio credentials, Twilio integration will be disabled")
        
        # Start the cleanup task
        asyncio.create_task(cleanup_stale_calls())
        
        logger.info("Twilio routes initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Twilio client: {str(e)}")
        # Set to None so we can check if it's available
        twilio_client = None

async def validate_twilio_request(request: Request) -> bool:
    """Validate that the request is coming from Twilio"""
    if not twilio_validator:
        logger.warning("Twilio validator not initialized, skipping request validation")
        return True
        
    try:
        # Get the URL and extract signature
        signature = request.headers.get("X-Twilio-Signature", "")
        
        # Get the full URL
        url = str(request.url)
        
        # For POST requests, we need the form data
        if request.method == "POST":
            form_data = await request.form()
            form_dict = dict(form_data)
            is_valid = twilio_validator.validate(url, form_dict, signature)
        else:
            # For GET requests
            is_valid = twilio_validator.validate(url, {}, signature)

        if not is_valid:
            logger.warning(f"Invalid Twilio signature: {signature}")

        return is_valid
    except Exception as e:
        logger.error(f"Error validating Twilio request: {str(e)}")
        return False

@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handles incoming Twilio voice calls with WebRTC integration."""
    logger.info(f"[TWILIO_CALL_SETUP] Received incoming call from {request.client.host}")

    # Validate that this request is coming from Twilio
    if not await validate_twilio_request(request):
        logger.warning("Invalid Twilio request signature")
        return Response(
            content=VoiceResponse().say("Unauthorized request").to_xml(),
            media_type="application/xml",
            status_code=403
        )

    # Check if Twilio client is initialized
    if not twilio_client:
        logger.error("Twilio client not initialized")
        return Response(
            content=VoiceResponse().say("Service unavailable").to_xml(),
            media_type="application/xml",
            status_code=503
        )

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
        
        # Also store in active_calls for cleanup later
        active_calls[call_sid] = {
            "peer_id": peer_id,
            "caller": caller,
            "start_time": time.time(),
            "last_activity": time.time()
        }

        # Get company API key from settings or use default
        company_api_key = getattr(settings, "DEFAULT_COMPANY_API_KEY", 
                                 "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35")

        # Get agent ID from settings or use default
        agent_id = getattr(settings, "DEFAULT_AGENT_ID", 
                          "049d0c12-a8d8-4245-b91e-d1e88adccdd5")

        # Construct WebRTC signaling URL
        host = request.headers.get("host") or request.base_url.hostname
        status_callback_url = f"https://{host}/api/v1/twilio/call-status"

        stream_url = f"wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}"
        logger.info(f"[TWILIO_CALL_SETUP] WebRTC Stream URL: {stream_url}")

        # Create TwiML response - NO SAY ELEMENT AT ALL
        resp = VoiceResponse()
        connect = Connect()
        connect.stream(url=stream_url)
        resp.append(connect)

        # Add status callback to TwiML
        resp.status_callback = status_callback_url
        resp.status_callback_method = "POST"
        resp.status_callback_event = "completed ringing in-progress answered busy failed no-answer canceled"

        # Log and return the TwiML
        resp_xml = resp.to_xml()
        logger.info(f"[TWILIO_CALL_SETUP] TwiML Response: {resp_xml}")

        return Response(content=resp_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"[TWILIO_CALL_SETUP] Error: {str(e)}", exc_info=True)
        return Response(
            content=VoiceResponse().say("An error occurred. Please try again later.").to_xml(),
            media_type="application/xml",
        )

@router.post("/call-status")
async def handle_call_status(request: Request):
    """Handle Twilio call status callbacks for resource cleanup."""
    # Validate the request is coming from Twilio
    if not await validate_twilio_request(request):
        return Response(status_code=403)
        
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        
        logger.info(f"Call status update for {call_sid}: {call_status}")
        
        # If call is completed or failed, clean up resources
        if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
            if call_sid in active_calls:
                peer_id = active_calls[call_sid].get("peer_id")
                
                # Remove from client_call_mapping if it exists
                if hasattr(request.app.state, 'client_call_mapping') and peer_id:
                    request.app.state.client_call_mapping.pop(peer_id, None)
                    
                # Remove from active_calls
                active_calls.pop(call_sid, None)
                
                logger.info(f"Cleaned up resources for call {call_sid}")
        
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling call status: {str(e)}")
        return Response(status_code=500)

async def cleanup_stale_calls():
    """Cleanup stale call mappings periodically"""
    while True:
        try:
            current_time = time.time()
            stale_call_sids = []
            
            # Find stale calls (inactive for more than 30 minutes)
            for call_sid, info in active_calls.items():
                if current_time - info.get("last_activity", 0) > 1800:  # 30 minutes
                    stale_call_sids.append(call_sid)
            
            # Remove stale calls
            for call_sid in stale_call_sids:
                info = active_calls.pop(call_sid, {})
                peer_id = info.get("peer_id")
                logger.info(f"Cleaned up stale call {call_sid} (peer {peer_id})")
                
            # Sleep for 5 minutes before next cleanup
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Error in call cleanup task: {e}")
            await asyncio.sleep(60)  # Shorter interval if there was an error

@router.get("/test-welcome-websocket")
def test_welcome_websocket(request: Request):
    """
    Returns TwiML that instructs Twilio to connect the call audio
    to a WebSocket endpoint. We'll send TTS audio from that endpoint.
    """
    host = request.headers.get("host") or request.url.netloc
    ws_url = f"wss://{host}/api/v1/twilio/test-websocket"
    status_callback_url = f"https://{host}/api/v1/twilio/call-status"
    
    logger.info(f"[TEST_WELCOME_WEBSOCKET] Using WebSocket URL: {ws_url}")

    # Build a TwiML response
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=ws_url)
    response.append(connect)
    
    # Add status callback
    response.status_callback = status_callback_url
    response.status_callback_method = "POST"
    response.status_callback_event = "completed ringing in-progress answered busy failed no-answer canceled"
    
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

    connected = False
    stream_sid = None
    last_activity = time.time()
    INACTIVITY_TIMEOUT = 60  # 60 seconds timeout

    try:
        while True:
            try:
                # Wait for messages from Twilio with a timeout
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=5.0  # 5 second timeout to check for inactivity
                )
                last_activity = time.time()

                data = json.loads(message)
                event_type = data.get("event")
                logger.debug(f"[TEST_WEBSOCKET] Received event: {event_type}")

                if event_type == "connected":
                    connected = True
                    logger.info("[TEST_WEBSOCKET] Received connected event")

                elif event_type == "start":
                    # Twilio provides the streamSid here
                    start_info = data.get("start", {})
                    stream_sid = start_info.get("streamSid")
                    logger.info(f"[TEST_WEBSOCKET] Stream started with SID: {stream_sid}")

                    try:
                        # Import here to avoid circular imports
                        from services.speech.tts_service import TextToSpeechService
                        tts_service = TextToSpeechService()
                        
                        welcome_text = "Hello! This is a single-chunk welcome message over the WebSocket."
                        logger.info("[TEST_WEBSOCKET] Generating TTS audio...")
                        
                        mp3_bytes = await tts_service.generate_audio(welcome_text)
                        if not mp3_bytes:
                            logger.error("[TEST_WEBSOCKET] Failed to generate audio")
                            continue

                        logger.info("[TEST_WEBSOCKET] Converting audio for Twilio...")
                        mu_law_audio = await tts_service.convert_audio_for_twilio(mp3_bytes)
                        if not mu_law_audio:
                            logger.error("[TEST_WEBSOCKET] Failed to convert audio")
                            continue

                        # Base64-encode and send as 'media' event
                        encoded_audio = base64.b64encode(mu_law_audio).decode("utf-8")
                        media_message = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": encoded_audio}
                        }

                        logger.info("[TEST_WEBSOCKET] Sending audio to Twilio...")
                        await websocket.send_text(json.dumps(media_message))
                        logger.info("[TEST_WEBSOCKET] Sent audio successfully (Sent single-chunk TTS audio.)")

                        # Optionally Send a 'mark' event to track playback
                        mark_message = {
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": "test-welcome-mark"}
                        }
                        await websocket.send_text(json.dumps(mark_message))
                        logger.info("[TEST_WEBSOCKET] Sent mark event")

                    except ImportError as e:
                        logger.error(f"[TEST_WEBSOCKET] Failed to import TTS service: {e}")
                    except Exception as e:
                        logger.error(f"[TEST_WEBSOCKET] Error processing audio: {e}", exc_info=True)

                elif event_type == "stop":
                    logger.info("[TEST_WEBSOCKET] Received 'stop' event from Twilio. Ending stream.")
                    break

                elif event_type == "media":
                    # Handle incoming audio if needed
                    logger.debug("[TEST_WEBSOCKET] Received media event")
                    pass

            except asyncio.TimeoutError:
                # Check for inactivity
                if time.time() - last_activity > INACTIVITY_TIMEOUT:
                    logger.warning("[TEST_WEBSOCKET] Connection inactive, closing")
                    break
                continue
                
            except json.JSONDecodeError as e:
                logger.error(f"[TEST_WEBSOCKET] Invalid JSON: {e}")
                continue

    except WebSocketDisconnect:
        logger.warning("[TEST_WEBSOCKET] WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[TEST_WEBSOCKET] Error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("[TEST_WEBSOCKET] Connection closed.")

@router.on_event("shutdown")
async def shutdown_event():
    global twilio_client
    
    try:
        # Clean up any active calls if possible
        if twilio_client:
            for call_sid in list(active_calls.keys()):
                try:
                    logger.info(f"Call {call_sid} marked for cleanup during shutdown")
                except Exception as e:
                    logger.error(f"Error cleaning up call {call_sid}: {e}")
        
        # Clear the client reference
        twilio_client = None
        logger.info("Twilio resources cleaned up")
    except Exception as e:
        logger.error(f"Error during Twilio shutdown: {e}")