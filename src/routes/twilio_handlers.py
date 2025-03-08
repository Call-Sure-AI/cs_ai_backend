from fastapi import APIRouter, WebSocket, Form, Request
from twilio.twiml.voice_response import VoiceResponse, Start
from twilio.rest import Client
from typing import Optional
import logging
import json
import uuid
from managers.connection_manager import ConnectionManager
from config.settings import settings
from routes.webrtc_handlers import router as webrtc_router
from services.webrtc.manager import WebRTCManager

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

@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice calls"""
    logger.info(f"Received incoming call from {request.client.host}")
    
    try:
        # Log request details
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Base URL: {request.base_url}")
        
        # Generate a peer ID for this call
        peer_id = f"twilio_{str(uuid.uuid4())}"
        
        # Use the WebRTC signaling endpoint
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"  # Use your default company key
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"  # Use your default agent
        
        # WebRTC endpoint URL
        stream_url = f'wss://{request.base_url.hostname}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}'
        logger.info(f"Setting up WebRTC stream URL: {stream_url}")
        
        # Create TwiML response
        resp = VoiceResponse()
        start = Start()
        start.stream(url=stream_url)
        resp.append(start)
        
        # Add initial message
        resp.say('Hello, I am your AI assistant. How can I help you today?')
        logger.info("TwiML response generated successfully")
        
        return resp.to_xml()
    
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}", exc_info=True)
        
        resp = VoiceResponse()
        resp.say('An error occurred. Please try again later.')
        return resp.to_xml()

@router.websocket("/stream")
async def handle_stream(websocket: WebSocket):
    """Handle WebSocket connection for Twilio Media Stream"""
    global manager
    client_id = None
    
    logger.info(f"New WebSocket connection attempt from {websocket.client.host}")
    
    try:
        # Get connection manager from app state
        if not manager:
            logger.info("Initializing connection manager from app state")
            manager = websocket.app.state.connection_manager
            if not manager:
                logger.critical("Connection manager not found in app state!")
                await websocket.close(code=1011)
                return
        
        await websocket.accept()
        logger.info("WebSocket connection accepted")
        
        # Generate client ID for this call
        client_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"Generated new client ID: {client_id}")
        
        # Initialize mock company for Twilio calls
        # This is important since your connection manager expects company info
        company_info = {
            "id": "twilio_company",
            "name": "Twilio Caller"
        }
        manager.client_companies[client_id] = company_info
        
        # Connect client to manager
        await manager.connect(websocket, client_id)
        logger.info(f"Client {client_id} connected to manager")
        
        # Initialize agent resources for Twilio client
        # Get a default agent for processing
        agent = await manager.agent_manager.get_base_agent(company_info["id"])
        if not agent:
            # Create a temporary agent if none exists
            agent = {
                "id": "twilio_agent",
                "name": "Twilio Assistant"
            }
        
        # Initialize agent resources for this client
        success = await manager.initialize_agent_resources(client_id, company_info["id"], agent)
        if not success:
            logger.error(f"Failed to initialize agent resources for {client_id}")
            await websocket.close(code=1011)
            return
        
        message_count = 0
        while True:
            # Receive audio data from Twilio
            data = await websocket.receive_bytes()
            message_count += 1
            
            if message_count % 100 == 0:  # Log every 100th message to avoid spam
                logger.info(f"Received audio data chunk #{message_count} for client {client_id}")
            
            # Process audio through your existing pipeline
            # We're simulating a text message since your manager expects a message
            message_data = {
                "type": "message",
                "message": f"Audio data chunk #{message_count}",  # This would be the transcribed audio in production
                "source": "twilio"
            }
            
            # Process using your existing connection manager
            await manager.process_streaming_message(client_id, message_data)
            
    except Exception as e:
        logger.error(f"Error in stream handler for client {client_id}: {str(e)}", exc_info=True)
        logger.info(f"WebSocket connection details during error: {websocket.client}")
    finally:
        if client_id and manager:
            logger.info(f"Disconnecting client {client_id}")
            # Clean up resources
            await manager.cleanup_agent_resources(client_id)
            manager.disconnect(client_id)
            logger.info(f"Total messages processed for client {client_id}: {message_count}")


@router.post("/call-status")
async def handle_call_status(
    CallStatus: str = Form(...),
    CallSid: str = Form(...),
    request: Request = None
):
    """Handle call status updates"""
    logger.info(f"Call status update received - SID: {CallSid}, Status: {CallStatus}")
    
    try:
        # Log additional call details if available
        form_data = await request.form() if request else {}
        relevant_fields = {
            'Duration', 'CallDuration', 'Timestamp', 'Called', 'Caller', 
            'Direction', 'SequenceNumber'
        }
        
        call_details = {
            key: form_data.get(key) 
            for key in relevant_fields 
            if key in form_data
        }
        
        if call_details:
            logger.info(f"Additional call details for {CallSid}: {json.dumps(call_details)}")
            
        # Log specific status transitions
        if CallStatus == "completed":
            logger.info(f"Call {CallSid} completed successfully")
        elif CallStatus == "failed":
            logger.warning(f"Call {CallSid} failed")
        elif CallStatus == "busy" or CallStatus == "no-answer":
            logger.warning(f"Call {CallSid} not connected - Status: {CallStatus}")
            
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing call status for {CallSid}: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# Add startup and shutdown logging
@router.on_event("startup")
async def startup_event():
    logger.info("Twilio routes initialized")
    logger.info(f"Using Twilio account: {settings.TWILIO_ACCOUNT_SID}")

@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")
    if manager:
        active_connections = len(manager.active_connections)
        logger.warning(f"Shutting down with {active_connections} active connections")
    

# Modified incoming-call handler
@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice calls"""
    logger.info(f"Received incoming call from {request.client.host}")
    
    try:
        # Log request details
        form_data = await request.form()
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Base URL: {request.base_url}")
        logger.info(f"Form data: {dict(form_data)}")
        
        # Get CallSid for tracking
        call_sid = form_data.get('CallSid', 'unknown_call')
        logger.info(f"Processing call with SID: {call_sid}")
        
        # Generate a peer ID for this call
        peer_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"Generated peer_id: {peer_id}")
        
        # Use the WebRTC signaling endpoint
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"
        
        # WebRTC endpoint URL - use public HTTPS URL with correct path
        host = request.headers.get("host") or request.base_url.hostname
        stream_url = f'wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}'
        logger.info(f"Setting up WebRTC stream URL: {stream_url}")
        
        # Store the peer_id in a persistent storage to track this call
        # For demo, we could use a global dict, but in production use Redis or a database
        # call_tracking[call_sid] = peer_id
        
        # Create TwiML response with stream
        resp = VoiceResponse()
        
        # Add the stream first - important to establish connection before any audio plays
        start = Start()
        start.stream(url=stream_url)
        resp.append(start)
        
        # Add initial message after stream is established
        resp.say('Hello, I am your AI assistant. How can I help you today?')
        
        # Log the generated TwiML
        twiml_response = resp.to_xml()
        logger.info(f"Generated TwiML: {twiml_response}")
        logger.info("TwiML response generated successfully")
        
        return twiml_response
    
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}", exc_info=True)
        
        resp = VoiceResponse()
        resp.say('An error occurred. Please try again later.')
        return resp.to_xml()

# Modified test endpoint with debugging capability
@router.post("/test-incoming-call")
async def test_incoming_call(request: Request):
    """Test endpoint for Twilio calls with debug information"""
    try:
        form_data = await request.form()
        logger.info(f"Test call request headers: {dict(request.headers)}")
        logger.info(f"Test call form data: {dict(form_data)}")
        
        # Create peer ID for testing
        peer_id = f"test_{str(uuid.uuid4())}"
        
        # Create TwiML response
        resp = VoiceResponse()
        start = Start()
        
        # Use the echo endpoint for testing
        host = request.headers.get("host") or request.base_url.hostname
        stream_url = f'wss://{host}/api/v1/twilio/echo-stream'
        logger.info(f"Setting up test stream URL: {stream_url}")
        
        start.stream(url=stream_url)
        resp.append(start)
        
        resp.say('This is a test call with echo functionality. Please speak after the beep.')
        resp.play('https://demo.twilio.com/docs/classic.mp3')  # Add a tone
        
        # Log the generated TwiML
        twiml_response = resp.to_xml()
        logger.info(f"Generated test TwiML: {twiml_response}")
        
        return twiml_response
        
    except Exception as e:
        logger.error(f"Error in test call: {str(e)}", exc_info=True)
        resp = VoiceResponse()
        resp.say('An error occurred during the test.')
        return resp.to_xml()

# Enhanced echo stream with better logging
@router.websocket("/echo-stream")
async def echo_stream(websocket: WebSocket):
    """Enhanced echo handler for testing Twilio Media Stream"""
    connection_id = str(uuid.uuid4())[:8]
    message_count = 0
    
    try:
        logger.info(f"[{connection_id}] Echo stream connection attempt from {websocket.client.host}")
        await websocket.accept()
        logger.info(f"[{connection_id}] Echo WebSocket connection accepted")
        
        # Send a confirmation message
        await websocket.send_text(json.dumps({
            "type": "echo_ready",
            "message": "Echo server ready to receive audio"
        }))
        logger.info(f"[{connection_id}] Sent ready message")
        
        # Simple echo loop with enhanced debugging
        while True:
            try:
                message = await websocket.receive()
                message_count += 1
                
                # Log periodically to avoid flooding logs
                if message_count == 1 or message_count % 100 == 0:
                    logger.info(f"[{connection_id}] Echo message #{message_count}, type: {message.get('type', 'unknown')}")
                
                # Echo back the same data type
                if message.get('type') == 'websocket.receive':
                    if 'bytes' in message:
                        # We received binary data (likely audio)
                        await websocket.send_bytes(message['bytes'])
                    elif 'text' in message:
                        # We received text data (likely control messages)
                        text_data = message['text']
                        logger.info(f"[{connection_id}] Received text: {text_data[:100]}...")
                        await websocket.send_text(text_data)
                        
                        # Try to parse JSON for more detailed logging
                        try:
                            json_data = json.loads(text_data)
                            if json_data.get('event') == 'start':
                                logger.info(f"[{connection_id}] Stream START event received")
                            elif json_data.get('event') == 'stop':
                                logger.info(f"[{connection_id}] Stream STOP event received")
                        except:
                            pass
                
            except Exception as e:
                logger.error(f"[{connection_id}] Error in echo loop: {str(e)}")
                break
                
    except Exception as e:
        logger.error(f"[{connection_id}] Error in echo handler: {str(e)}")
    finally:
        logger.info(f"[{connection_id}] Echo WebSocket closed after {message_count} messages")