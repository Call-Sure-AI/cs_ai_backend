from fastapi import APIRouter, WebSocket, Form, Request
from twilio.twiml.voice_response import VoiceResponse, Start
from twilio.rest import Client
from typing import Optional
import logging
import json
import uuid
from managers.connection_manager import ConnectionManager
from config.settings import settings

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
        logger.debug(f"Request headers: {dict(request.headers)}")
        logger.debug(f"Base URL: {request.base_url}")
        
        resp = VoiceResponse()
        start = Start()
        
        # Create WebSocket connection for stream
        stream_url = f'wss://{request.base_url.hostname}/api/twilio/stream'
        logger.debug(f"Setting up stream URL: {stream_url}")
        
        start.stream(url=stream_url)
        resp.append(start)
        
        # Add initial message
        resp.say('Hello, I am your AI assistant. How can I help you today?')
        logger.info("TwiML response generated successfully")
        
        return resp.to_xml()
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}", exc_info=True)
        logger.debug(f"Request data during error: {await request.body()}")
        
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
        if not manager:
            logger.debug("Initializing connection manager from app state")
            manager = websocket.app.state.connection_manager
        
        await websocket.accept()
        logger.debug("WebSocket connection accepted")
        
        # Generate client ID for this call
        client_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"Generated new client ID: {client_id}")
        
        await manager.connect(websocket, client_id)
        logger.debug(f"Client {client_id} connected to manager")
        
        message_count = 0
        while True:
            # Receive audio data from Twilio
            data = await websocket.receive_bytes()
            message_count += 1
            
            if message_count % 100 == 0:  # Log every 100th message to avoid spam
                logger.debug(f"Received audio data chunk #{message_count} for client {client_id}")
            
            # Process audio through your existing pipeline
            message_data = {
                "type": "audio",
                "content": data,
                "source": "twilio"
            }
            
            await manager.process_streaming_message(client_id, message_data)
            
    except Exception as e:
        logger.error(f"Error in stream handler for client {client_id}: {str(e)}", exc_info=True)
        logger.debug(f"WebSocket connection details during error: {websocket.client}")
    finally:
        if client_id:
            logger.info(f"Disconnecting client {client_id}")
            manager.disconnect(client_id)
            logger.debug(f"Total messages processed for client {client_id}: {message_count}")

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
            logger.debug(f"Additional call details for {CallSid}: {json.dumps(call_details)}")
            
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
    logger.debug(f"Using Twilio account: {settings.TWILIO_ACCOUNT_SID}")

@router.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Twilio routes")
    if manager:
        active_connections = len(manager.active_connections)
        logger.warning(f"Shutting down with {active_connections} active connections")