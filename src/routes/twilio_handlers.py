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
        
        
        
@router.websocket("/echo-stream")
async def echo_stream(websocket: WebSocket):
    """Simple echo handler for testing Twilio Media Stream"""
    try:
        await websocket.accept()
        logger.info("Echo WebSocket connection accepted")
        
        # Send a confirmation message
        await websocket.send_text(json.dumps({"type": "echo_ready"}))
        
        # Simple echo loop
        while True:
            try:
                data = await websocket.receive()
                logger.info(f"Echo received: {data.get('type', 'unknown')}")
                
                # Echo back the same data type
                if data.get('type') == 'websocket.receive':
                    if 'bytes' in data:
                        await websocket.send_bytes(data['bytes'])
                    elif 'text' in data:
                        await websocket.send_text(data['text'])
                
            except Exception as e:
                logger.error(f"Error in echo loop: {str(e)}")
                break
                
    except Exception as e:
        logger.error(f"Error in echo handler: {str(e)}")
    finally:
        logger.info("Echo WebSocket closed")
        
        
@router.post("/test-incoming-call")
async def test_incoming_call(request: Request):
    """Test endpoint for Twilio calls with simplified stream"""
    try:
        resp = VoiceResponse()
        start = Start()
        
        # Use the echo endpoint instead
        stream_url = f'wss://{request.base_url.hostname}/api/v1/twilio/echo-stream'
        logger.info(f"Setting up test stream URL: {stream_url}")
        
        start.stream(url=stream_url)
        resp.append(start)
        
        resp.say('This is a test call with echo functionality.')
        
        return resp.to_xml()
        
    except Exception as e:
        logger.error(f"Error in test call: {str(e)}")
        resp = VoiceResponse()
        resp.say('An error occurred during the test.')
        return resp.to_xml()