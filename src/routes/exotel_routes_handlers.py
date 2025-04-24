"""
Exotel integration for voice calls with support for AI-powered conversations.

This module provides a complete implementation for handling Exotel voice calls:
1. Incoming call webhook handler
2. Call status callback handler
3. Audio streaming endpoint for real-time STT and TTS
4. Connection management between Exotel and the AI backend

The implementation leverages the existing architecture components:
- ConnectionManager for managing AI agent interactions
- Speech recognition and transcription services
- Text-to-speech services

Flow:
1. Exotel calls our webhook when an incoming call is received
2. We respond with TwiML-like AppML to connect the call to our WebSocket endpoint
3. The WebSocket receives audio from Exotel and processes it with our STT service
4. The transcribed text is sent to our AI services for processing
5. The AI response is converted to speech and streamed back to the caller
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Form, Request
from fastapi.responses import Response, JSONResponse
import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from managers.connection_manager import ConnectionManager
from services.speech.deepgram_ws_service import DeepgramWebSocketService
from services.speech.tts_service import WebSocketTTSService
from config.settings import settings
from database.config import get_db
from database.models import Company, Agent


# Initialize router and logging
router = APIRouter()
logger = logging.getLogger(__name__)

# Global variables - will be initialized during startup
exotel_client = None
manager: Optional[ConnectionManager] = None
active_calls: Dict[str, Dict[str, Any]] = {}
audio_buffers: Dict[str, bytes] = {}

# Exotel credentials
EXOTEL_SID = os.getenv("EXOTEL_SID")
EXOTEL_TOKEN = os.getenv("EXOTEL_TOKEN")
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY")

# Other configuration
DEFAULT_COMPANY_API_KEY = getattr(settings, "DEFAULT_COMPANY_API_KEY", 
                                "8a638fd6a20a9edbe5228bf6c364e44aa10b01f17d7a62b4826ce6cd1593242e")
DEFAULT_AGENT_ID = getattr(settings, "DEFAULT_AGENT_ID", 
                          "48111553-4b98-4f4e-9431-f6ab6cbcfacf")

# # Helper function to validate incoming Exotel requests - similar to Twilio validation
# async def validate_exotel_request(request: Request) -> bool:
#     """Validate that the request is coming from Exotel"""
#     # For Exotel, this would typically include checking for an auth token
#     # or signature in the request headers, but implementation may vary
#     try:
#         # Implementation depends on Exotel's authentication mechanism
#         # This is a simplified version - implement properly according to Exotel docs
#         # If Exotel uses a signature system similar to Twilio:
#         logger.info(f"ENV check - EXOTEL_SID: {'Set' if EXOTEL_SID else 'Not set'}")
#         logger.info(f"ENV check - EXOTEL_TOKEN: {'Set' if EXOTEL_TOKEN else 'Not set'}")
#         logger.info(f"ENV check - EXOTEL_API_KEY: {'Set' if EXOTEL_API_KEY else 'Not set'}")

#         signature = request.headers.get("X-Exotel-Signature", "")
#         if not signature and EXOTEL_API_KEY:
#             logger.warning(f"Invalid Exotel signature: {signature}")
#             return False
#         return True
#     except Exception as e:
#         logger.error(f"Error validating Exotel request: {str(e)}")
#         return False

async def validate_exotel_request(request: Request) -> bool:
    """Temporarily skip Exotel validation — enable real check later if needed"""
    logger.info("Skipping Exotel request validation for development")
    return True


@router.on_event("startup")
async def startup_event():
    """Initialize resources when the server starts"""
    global manager
    
    try:
        # Check if we have the required settings
        if EXOTEL_SID and EXOTEL_TOKEN:
            # Initialize any necessary Exotel client or libraries
            # Note: Depending on the Exotel SDK, this might be a synchronous call
            # Ideally, it should be initialized in a separate thread if it's blocking
            logger.info("Exotel credentials found")
        else:
            logger.warning("Missing Exotel credentials, Exotel integration will be disabled")
        
        # Start the cleanup task
        asyncio.create_task(cleanup_stale_calls())
        
        logger.info("Exotel routes initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Exotel integration: {str(e)}")

@router.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handles incoming Exotel voice calls by generating AppML response"""
    logger.info(f"[EXOTEL_CALL_SETUP] Received incoming call")

    # Validate that this request is coming from Exotel
    if not await validate_exotel_request(request):
        logger.warning("Invalid Exotel request")
        return Response(
            content="<Response><Say>Unauthorized request</Say></Response>",
            media_type="application/xml",
            status_code=403
        )

    try:
        # Parse form data from the request
        if request.method == "POST":
            form_data = await request.form()
            call_sid = form_data.get("CallSid", form_data.get("sid", "unknown_call"))
            caller = form_data.get("From", form_data.get("from", "unknown"))
        else:
            query_params = dict(request.query_params)
            call_sid = query_params.get("CallSid", query_params.get("sid", "unknown_call"))
            caller = query_params.get("From", query_params.get("from", "unknown"))

        logger.info(f"[EXOTEL_CALL_SETUP] Call SID: {call_sid}, Caller: {caller}")

        # Generate unique WebSocket peer ID
        peer_id = f"exotel_{str(uuid.uuid4())}"
        logger.info(f"[EXOTEL_CALL_SETUP] Generated Peer ID: {peer_id}")

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

        # Get company API key and agent ID from settings or use default
        company_api_key = DEFAULT_COMPANY_API_KEY
        agent_id = DEFAULT_AGENT_ID

        # Construct WebSocket signaling URL
        host = request.headers.get("host") or request.url.netloc
        status_callback_url = f"https://{host}/api/v1/exotel/call-status"

        # WebRTC Stream URL (this would be your WebSocket endpoint for streaming audio)
        stream_url = f"wss://{host}/api/v1/exotel/stream/{peer_id}/{company_api_key}/{agent_id}"
        logger.info(f"[EXOTEL_CALL_SETUP] WebSocket Stream URL: {stream_url}")

        # Create AppML response for Exotel (similar to TwiML but for Exotel)
        # Note: The exact format depends on Exotel's documentation
        # This is an example based on common XML formats
        appml_response = f"""
        <Response>
            <Connect>
                <Stream url="{stream_url}" />
            </Connect>
            <Set>
                <statusCallback url="{status_callback_url}" method="POST" events="completed,ringing,in-progress,answered,busy,failed,no-answer,canceled" />
            </Set>
        </Response>
        """
        
        # Log and return the AppML
        logger.info(f"[EXOTEL_CALL_SETUP] AppML Response: {appml_response}")
        
        return Response(
            content=appml_response, 
            media_type="application/xml"
        )

    except Exception as e:
        logger.error(f"[EXOTEL_CALL_SETUP] Error: {str(e)}", exc_info=True)
        return Response(
            content="<Response><Say>An error occurred. Please try again later.</Say></Response>",
            media_type="application/xml",
        )

@router.api_route("/call-status", methods=["GET", "POST"])
async def handle_call_status(request: Request):
    """Handle Exotel call status callbacks for resource cleanup"""
    # Validate the request is coming from Exotel
    if not await validate_exotel_request(request):
        return Response(status_code=403)
        
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid", form_data.get("sid"))
        call_status = form_data.get("CallStatus", form_data.get("status"))
        
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

@router.websocket("/stream/{peer_id}/{company_api_key}/{agent_id}")
async def exotel_audio_stream(
    websocket: WebSocket,
    peer_id: str,
    company_api_key: str,
    agent_id: str
):
    """WebSocket endpoint for two-way audio streaming with Exotel"""
    app = websocket.app  # Get FastAPI app instance
    connection_manager = app.state.connection_manager
    connection_id = str(uuid.uuid4())[:8]
    
    # Create Deepgram speech service for STT
    speech_service = DeepgramWebSocketService()
    
    # Initialize flags and state
    connected = False
    websocket_closed = False
    last_speech_time = time.time()
    is_processing = False
    silence_threshold = 2.0  # Silence detection threshold in seconds
    welcome_sent = False
    
    try:
        logger.info(f"[{connection_id}] Handling Exotel call for {peer_id}")
        
        # Accept the WebSocket connection
        await websocket.accept()
        connected = True

        # Send handshake message immediately after accept
        await websocket.send_text(json.dumps({
            "event": "connected",
            "protocol": "websocket",
            "version": "1.0.0"
        }))
        # Get company info from the API key
        if not connection_manager:
            logger.error(f"[{connection_id}] Connection manager not found!")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        # Get company and prepare info
        db = next(get_db())
        company = db.query(Company).filter_by(api_key=company_api_key).first()
        
        if not company:
            logger.error(f"[{connection_id}] Company not found for API key: {company_api_key}")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        # Set company info
        company_info = {
            "id": company.id,
            "name": company.name or "Customer Support"
        }
        
        # Register with connection manager
        connection_manager.client_companies[peer_id] = company_info
        await connection_manager.connect(websocket, peer_id)
        logger.info(f"[{connection_id}] Client {peer_id} connected")
        
        # Get agent and set up AI resources
        agent_record = db.query(Agent).filter_by(id=agent_id).first()
        if not agent_record:
            logger.error(f"[{connection_id}] Agent not found with ID: {agent_id}")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        # Extract context from agent info
        additional_context = agent_record.additional_context or {}
        business_context = additional_context.get('businessContext', '')
        role_description = additional_context.get('roleDescription', '')
        
        # Create prompt for the agent
        prompt = agent_record.prompt
        if business_context and role_description:
            prompt = f"{business_context} {role_description}"
        elif business_context:
            prompt = business_context
        elif role_description:
            prompt = role_description
        
        # Create agent info
        agent = {
            "id": agent_record.id,
            "name": agent_record.name,
            "type": agent_record.type,
            "prompt": prompt,
            "confidence_threshold": agent_record.confidence_threshold,
            "additional_context": agent_record.additional_context
        }
        
        # Initialize agent resources
        success = await connection_manager.initialize_agent_resources(peer_id, company_info["id"], agent)
        if not success:
            logger.error(f"[{connection_id}] Failed to initialize agent resources")
            await websocket.close(code=1011)
            websocket_closed = True
            return
        
        # Define the transcription callback function
        async def handle_transcription(session_id, transcribed_text):
            """Handle transcripts from STT service"""
            nonlocal is_processing, last_speech_time
            
            # Update last speech time for silence detection
            last_speech_time = time.time()
            
            # If empty text is returned, it might indicate end of utterance
            if not transcribed_text or not transcribed_text.strip():
                return
                
            logger.info(f"[{connection_id}] TRANSCRIBED: '{transcribed_text}'")
            
            is_processing = True
            
            # Create message data for AI processing
            message_data = {
                "type": "message",
                "message": transcribed_text,
                "source": "exotel"
            }
            
            # Process the speech through AI and TTS
            try:
                await process_message_with_audio_response(
                    connection_manager, 
                    peer_id, 
                    message_data, 
                    websocket
                )
            except Exception as e:
                logger.error(f"[{connection_id}] Error processing message: {str(e)}")
            finally:
                is_processing = False
        
        # Initialize STT session
        logger.info(f"[{connection_id}] Initializing Deepgram session")
        init_success = await speech_service.initialize_session(peer_id, handle_transcription)
        
        if not init_success:
            logger.error(f"[{connection_id}] Failed to initialize speech recognition")
            await websocket.close(code=1011)
            websocket_closed = True
            return
            
        logger.info(f"[{connection_id}] Speech recognition initialized successfully")
        
        # Send welcome message immediately
        if not welcome_sent:
            welcome_data = {"type": "message", "message": "__SYSTEM_WELCOME__", "source": "exotel"}
            asyncio.create_task(process_message_with_audio_response(
                connection_manager, peer_id, welcome_data, websocket
            ))
            welcome_sent = True
        
        # Main message processing loop
        while not websocket_closed:
            try:
                # Wait for incoming messages with a timeout
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                
                if message.get('type') == 'websocket.disconnect':
                    logger.info(f"[{connection_id}] Received disconnect message")
                    websocket_closed = True
                    break
                
                # Handle binary audio data
                if 'bytes' in message:
                    audio_data = message['bytes']
                    logger.debug(f"[{connection_id}] Received audio chunk with size {len(audio_data)}")
                    
                    # Process the audio through STT service
                    await speech_service.process_audio_chunk(peer_id, audio_data)
                    last_speech_time = time.time()
                
                # Handle JSON text messages
                elif 'text' in message:
                    try:
                        data = json.loads(message['text'])
                        event = data.get('event')
                        
                        if event in ['connected', 'start', 'stop']:
                            logger.info(f"[{connection_id}] Exotel event: {event}")
                        
                        if event == 'start':
                            # Extract stream ID from Exotel start event
                            stream_sid = data.get('streamSid', data.get('sid'))
                            if stream_sid:
                                # Store stream ID for later use
                                if not hasattr(app.state, 'stream_sids'):
                                    app.state.stream_sids = {}
                                app.state.stream_sids[peer_id] = stream_sid
                            
                            # Also store call SID if provided
                            call_sid = data.get('callSid', data.get('CallSid'))
                            if call_sid:
                                if not hasattr(app.state, 'client_call_mapping'):
                                    app.state.client_call_mapping = {}
                                app.state.client_call_mapping[peer_id] = call_sid
                            
                            # Send connected response if needed
                            if not connected:
                                await websocket.send_text(json.dumps({
                                    "event": "connected",
                                    "protocol": "websocket",
                                    "version": "1.0.0"
                                }))
                                connected = True
                        
                        elif event == 'media':
                            # Handle media payloads - this may vary based on Exotel's implementation
                            # Convert audio to the format expected by our speech recognition service
                            media_data = data.get('media', {})
                            payload = media_data.get('payload')
                            
                            if payload:
                                # Convert Exotel audio format if needed
                                audio_data = await speech_service.convert_twilio_audio(payload, peer_id)
                                if audio_data:
                                    # Process audio through STT
                                    await speech_service.process_audio_chunk(peer_id, audio_data)
                                    last_speech_time = time.time()
                        
                        elif event == 'stop':
                            logger.info(f"[{connection_id}] Call ended")
                            websocket_closed = True
                            break
                    
                    except json.JSONDecodeError:
                        logger.warning(f"[{connection_id}] Invalid JSON received")
                
                # Check for connection health
                if connection_manager.websocket_is_closed(websocket):
                    logger.warning(f"[{connection_id}] WebSocket detected as closed")
                    websocket_closed = True
                    break
            
            except asyncio.TimeoutError:
                # Just a timeout in the receive loop, continue
                # Check for silence to trigger processing
                current_time = time.time()
                silence_duration = current_time - last_speech_time
                
                if silence_duration >= silence_threshold and not is_processing:
                    # If there's silence and we're not already processing, check if we have
                    # a pending transcript to process
                    logger.info(f"[{connection_id}] Silence detected, checking for pending transcripts")
                
            except Exception as e:
                logger.error(f"[{connection_id}] Error in message loop: {str(e)}")
                websocket_closed = True
                break
    
    except Exception as e:
        logger.error(f"[{connection_id}] Error in Exotel handler: {str(e)}")
    
    finally:
        # Cleanup
        await speech_service.close_session(peer_id)
        
        if peer_id and connection_manager:
            logger.info(f"[{connection_id}] Disconnecting client {peer_id}")
            try:
                await connection_manager.cleanup_agent_resources(peer_id)
                connection_manager.disconnect(peer_id)
            except Exception as e:
                logger.error(f"[{connection_id}] Error during cleanup: {str(e)}")
        
        logger.info(f"[{connection_id}] Call ended")

async def process_message_with_audio_response(
    connection_manager: ConnectionManager,
    peer_id: str,
    message_data: dict,
    websocket: WebSocket
):
    """Process an AI message and respond with audio over the WebSocket"""
    msg_id = str(time.time())  # Generate a unique message ID
    
    try:
        # Get agent resources
        agent_res = connection_manager.agent_resources.get(peer_id)
        if not agent_res:
            logger.error(f"No agent resources found for {peer_id}")
            return
            
        chain = agent_res.get('chain')
        rag_service = agent_res.get('rag_service')
        
        if not chain or not rag_service:
            logger.error(f"Missing chain or rag service for {peer_id}")
            return
        
        # Initialize TTS service
        tts_service = WebSocketTTSService()
        
        # Get stream SID (needed for Exotel media messages)
        app = websocket.app
        stream_sid = app.state.stream_sids.get(peer_id, "")
        
        # Define callback for sending audio to Exotel
        async def send_audio_to_exotel(audio_base64):
            try:
                # For logging purposes
                if not hasattr(send_audio_to_exotel, "chunk_count"):
                    send_audio_to_exotel.chunk_count = 0
                
                send_audio_to_exotel.chunk_count += 1
                chunk_count = send_audio_to_exotel.chunk_count
                
                # Create media message for Exotel (similar to Twilio format)
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": audio_base64}
                }
                
                # Send the audio data to Exotel
                await websocket.send_text(json.dumps(media_message))
                
                if chunk_count == 1:
                    logger.info(f"Sent first audio chunk to Exotel")
                
                return True
            except Exception as e:
                logger.error(f"Error sending audio to Exotel: {str(e)}")
                return False
        
        # Special handling for preset responses to minimize latency
        if message_data.get('message') == '__SYSTEM_WELCOME__':
            # Hardcoded welcome message
            welcome_text = "Hello! I'm your AI voice assistant. How may I help you today?"
            
            # Connect to TTS service
            connect_success = await tts_service.connect(send_audio_to_exotel)
            
            if connect_success:
                await tts_service.stream_text(welcome_text)
                # Give audio generation time to complete
                await asyncio.sleep(1.5)
                await tts_service.close()
            
            logger.info(f"Completed welcome response: {welcome_text}")
            return
        
        # Get conversation context if available
        conversation_context = {}
        conversation = connection_manager.client_conversations.get(peer_id)
        if conversation:
            conversation_context = await connection_manager.agent_manager.get_conversation_context(conversation['id'])
        
        # Connect to TTS service
        connect_success = await tts_service.connect(send_audio_to_exotel)
        if not connect_success:
            logger.error("Failed to connect to TTS service")
            return
        
        # Variables to track sentence accumulation for TTS
        full_response = ""
        current_sentence = ""
        
        # Stream response token by token
        async for token in rag_service.get_answer_with_chain(
            chain=chain,
            question=message_data.get('message', ''),
            conversation_context=conversation_context
        ):
            # Add token to text
            full_response += token
            current_sentence += token
            
            # Check if we have a complete sentence or significant pause
            if any(p in token for p in ".!?"):
                if current_sentence.strip():
                    logger.info(f"Sending to TTS: '{current_sentence}'")
                    await tts_service.stream_text(current_sentence)
                    current_sentence = ""  # Reset for next sentence
                    await asyncio.sleep(0.3)  # Small pause between sentences
            
            # Small delay
            await asyncio.sleep(0.01)
        
        # Process any remaining text
        if current_sentence.strip():
            await tts_service.stream_text(current_sentence)
            await asyncio.sleep(0.3)
        
        # Ensure all audio is processed
        await tts_service.flush()
        await asyncio.sleep(1.0)
        
        # Close TTS service
        await tts_service.stream_end()
        await asyncio.sleep(0.5)
        await tts_service.close()
        
        logger.info(f"Completed response: {full_response}")
        return full_response
    
    except Exception as e:
        logger.error(f"Error processing message with audio: {str(e)}")
        if 'tts_service' in locals() and tts_service is not None:
            await tts_service.close()
        return None

async def cleanup_stale_calls():
    """Periodically clean up stale call mappings"""
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
            
            # Sleep before next cleanup
            await asyncio.sleep(300)  # 5 minutes
        except Exception as e:
            logger.error(f"Error in call cleanup task: {e}")
            await asyncio.sleep(60)  # Shorter interval if there was an error

@router.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when server is shutting down"""
    try:
        # Clean up any active calls
        for call_sid in list(active_calls.keys()):
            try:
                logger.info(f"Call {call_sid} marked for cleanup during shutdown")
            except Exception as e:
                logger.error(f"Error cleaning up call {call_sid}: {e}")
        
        logger.info("Exotel resources cleaned up")
    except Exception as e:
        logger.error(f"Error during Exotel shutdown: {e}")

@router.get("/test")
async def test_exotel_integration():
    """Test endpoint to verify Exotel integration status"""
    return {
        "status": "ok", 
        "message": "Exotel integration is active", 
        "active_calls": len(active_calls)
    }

# Helper function to initiate outbound calls (requires Exotel API integration)
@router.post("/call")
async def initiate_call(request: Request):
    """Initiate an outbound call to a customer via Exotel"""
    try:
        data = await request.json()
        to_number = data.get("to_number")
        from_number = data.get("from_number", settings.EXOTEL_PHONE_NUMBER)
        callback_url = data.get("callback_url")
        
        if not to_number:
            return JSONResponse(
                status_code=400,
                content={"error": "to_number is required"}
            )
            
        if not EXOTEL_SID or not EXOTEL_TOKEN:
            return JSONResponse(
                status_code=503,
                content={"error": "Exotel credentials not configured"}
            )
            
        # This is a placeholder for the actual Exotel API call
        # You'll need to replace this with the actual API call based on Exotel's documentation
        # Example using requests (synchronous - consider using httpx for async):
        """
        import httpx
        
        url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect.json"
        auth = (EXOTEL_SID, EXOTEL_TOKEN)
        
        payload = {
            "From": from_number,
            "To": to_number,
            "CallerId": settings.EXOTEL_PHONE_NUMBER,
            "CallType": "trans",
            "StatusCallback": callback_url
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, auth=auth, data=payload)
            if response.status_code != 200:
                logger.error(f"Exotel API error: {response.text}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": "Failed to initiate call", "details": response.text}
                )
                
            call_data = response.json()
            return {"call_sid": call_data.get("Call", {}).get("Sid")}
        """
        
        # For now, return a mock response
        return {
            "status": "initiated",
            "call_sid": f"EX{uuid.uuid4().hex[:18]}",
            "to": to_number,
            "from": from_number
        }
        
    except Exception as e:
        logger.error(f"Error initiating call: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )