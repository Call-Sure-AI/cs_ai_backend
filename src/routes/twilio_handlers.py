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
from services.webrtc.manager import WebRTCManager
from services.speech.stt_service import SpeechToTextService
from services.speech.tts_service import TextToSpeechService
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

stt_service = SpeechToTextService()
tts_service = TextToSpeechService()


# In-memory storage to track active calls (in production, use Redis or a database)
active_calls: Dict[str, Dict[str, Any]] = {}

# Add to routes/twilio_handlers.py
async def handle_ai_response(client_id: str, text: str) -> bool:
    """
    Handle AI response for a Twilio call by sending TwiML for speech synthesis
    
    Args:
        client_id: The Twilio client ID
        text: The text to be spoken
        
    Returns:
        bool: Whether the operation was successful
    """
    try:
        logger.info(f"Handling AI response for {client_id}: {text[:50]}...")
        
        # Create a Twilio TwiML response
        response = VoiceResponse()
        
        # Add the speech synthesis
        response.say(text, voice='Polly.Matthew', language='en-US')
        
        # IMPORTANT: After speech, add a <gather> tag to listen for input
        # This keeps the call active waiting for user speech
        gather = response.gather(
            input='speech',
            action='/api/v1/twilio/gather',
            timeout=5,  # Wait 5 seconds for input
            speech_timeout='auto'  # Automatically detect end of speech
        )
        
        # For debugging, log the generated TwiML
        twiml = str(response)
        logger.debug(f"Generated TwiML: {twiml[:100]}...")
        
        # In a production implementation, you would send this TwiML to Twilio
        # For example, using webhook responses or through the Twilio API
        
        # Store the response in the active calls data
        if client_id not in active_calls:
            active_calls[client_id] = {
                "responses": []
            }
        
        active_calls[client_id]["responses"].append({
            "text": text,
            "twiml": twiml,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        return True
        
    except Exception as e:
        logger.error(f"Error handling AI response for {client_id}: {str(e)}", exc_info=True)
        return False

async def mark_call_complete(client_id: str) -> bool:
    """Mark a Twilio call as complete"""
    if client_id in active_calls:
        active_calls[client_id]["completed"] = True
        logger.info(f"Marked call {client_id} as complete")
        return True
    return False

def get_call_data(client_id: str) -> Optional[Dict[str, Any]]:
    """Get data for an active Twilio call"""
    return active_calls.get(client_id)


@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice calls with WebRTC integration"""
    logger.info(f"Received incoming call from {request.client.host}")
    
    try:
        # Log request details
        form_data = await request.form()
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Base URL: {request.base_url}")
        logger.info(f"Form data: {dict(form_data)}")
        
        # Get CallSid for tracking
        call_sid = form_data.get('CallSid', 'unknown_call')
        caller = form_data.get('From', 'unknown')
        logger.info(f"Processing call with SID: {call_sid} from {caller}")
        
        # Generate a peer ID for this call
        peer_id = f"twilio_{str(uuid.uuid4())}"
        logger.info(f"Generated peer_id: {peer_id}")
        
        # Store call information
        active_calls[call_sid] = {
            "peer_id": peer_id,
            "caller": caller,
            "start_time": form_data.get('Timestamp'),
            "status": "initiated",
            "last_activity": time.time()
        }
        
        # Register call with TTS service
        await tts_service.register_call(call_sid, peer_id)
        
        # Get host from headers or base URL
        host = request.headers.get("host") or request.base_url.hostname
        
        # For proper WebRTC integration, use the WebRTC signaling endpoint
        company_api_key = "3d19d78ad75671ad667e4058d9acfda346bd33946c565981c9a22194dfd55a35"
        agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"
        stream_url = f'wss://{host}/api/v1/webrtc/signal/{peer_id}/{company_api_key}/{agent_id}'
        logger.info(f"Setting up stream URL: {stream_url}")
        
        # Create TwiML response with stream
        resp = VoiceResponse()
        
        # IMPORTANT: Stream must be the first element in the TwiML response
        start = Start()
        # track="both" captures both inbound and outbound audio
        start.stream(url=stream_url, track="both") 
        resp.append(start)
        
        # Add initial greeting after stream is established
        resp.say('Hello, I am your AI assistant. How can I help you today?', voice='alice')
        resp.gather(input='speech', timeout=20, action='/api/v1/twilio/gather')

        # Log the generated TwiML
        twiml_response = resp.to_xml()
        logger.info(f"Generated TwiML: {twiml_response}")
        logger.info("TwiML response generated successfully")
        
        return Response(
            content=twiml_response,
            media_type="application/xml"
        )
    
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}", exc_info=True)
        
        resp = VoiceResponse()
        resp.say('An error occurred. Please try again later.', voice='alice')
        return Response(
            content=resp.to_xml(),
            media_type="application/xml"
        )


@router.post("/gather")
async def handle_gather(
    request: Request,
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
):
    """Handle speech recognition results from Twilio Gather verb"""
    try:
        logger.info(f"Received speech from Twilio: {SpeechResult}")
        
        # Get form data
        form_data = await request.form()
        logger.info(f"Gather form data: {dict(form_data)}")
        
        # Create a response
        resp = VoiceResponse()
        
        # If we have a speech result, process it with AI
        if SpeechResult and SpeechResult.strip():
            # Process the speech with AI and get a response
            try:
                # Create RAG service instance
                agent_id = "049d0c12-a8d8-4245-b91e-d1e88adccdd5"
                company_id = "cd34fe22-5a40-43ef-b979-7f13cb9e4caa"
                
                # Initialize RAG service
                from services.rag.rag_service import RAGService
                from services.vector_store.qdrant_service import QdrantService
                
                vector_store = QdrantService()
                rag_service = RAGService(vector_store)
                
                # Create QA chain
                chain = await rag_service.create_qa_chain(
                    company_id=company_id,
                    agent_id=agent_id
                )
                
                # Process the question and get response
                response_text = ""
                async for token in rag_service.get_answer_with_chain(
                    chain=chain,
                    question=SpeechResult,
                    company_name="Callsure AI"
                ):
                    response_text += token
                
                # Make sure we have a response
                if not response_text or response_text.strip() == "":
                    response_text = "I processed your input but don't have a specific response. How else can I help you?"
                    
                logger.info(f"Generated AI response: {response_text[:100]}...")
                
                # Add the AI response to the TwiML
                resp.say(response_text, voice='alice')
                
            except Exception as e:
                logger.error(f"Error processing AI response: {str(e)}")
                resp.say("I encountered an issue processing your request. How else can I help you?", voice='alice')
            
        else:
            # If no speech detected
            resp.say("I didn't catch that. Could you please speak again?", voice='alice')
        
        # Add a new Gather to continue listening
        resp.gather(input='speech', timeout=20, action='/api/v1/twilio/gather')
        
        # Store the call in active_calls for future reference
        if CallSid not in active_calls:
            peer_id = f"twilio_{str(uuid.uuid4())}"
            active_calls[CallSid] = {
                "peer_id": peer_id,
                "last_activity": time.time()
            }
        
        # Log the generated TwiML
        twiml_response = resp.to_xml()
        logger.info(f"Generated gather TwiML: {twiml_response}")
        
        return Response(
            content=twiml_response,
            media_type="application/xml"
        )
        
    except Exception as e:
        logger.error(f"Error in gather handler: {str(e)}", exc_info=True)
        
        resp = VoiceResponse()
        resp.say("I'm sorry, we encountered a technical issue. Please try again later.", voice='alice')
        
        return Response(
            content=resp.to_xml(),
            media_type="application/xml"
        )



@router.post("/test-incoming-call")
async def test_incoming_call(request: Request):
    """Test endpoint for Twilio calls with echo stream"""
    try:
        # Log request details
        form_data = await request.form()
        logger.info(f"Test call request headers: {dict(request.headers)}")
        logger.info(f"Test call form data: {dict(form_data)}")
        
        # Get CallSid for tracking
        call_sid = form_data.get('CallSid', 'unknown_call')
        logger.info(f"Processing test call with SID: {call_sid}")
        
        # Create TwiML response
        resp = VoiceResponse()
        
        # Create a <Stream> element - must be first in TwiML
        start = Start()
        
        # Use the echo endpoint for testing
        host = request.headers.get("host") or request.base_url.hostname
        stream_url = f'wss://{host}/api/v1/twilio/echo-stream'
        logger.info(f"Setting up test stream URL: {stream_url}")
        
        # Configure the Stream
        start.stream(url=stream_url, track="both")  # track="both" captures both inbound and outbound audio
        resp.append(start)
        
        # Add voice instructions after the stream
        resp.say('This is a test call. Please speak after the beep.')
        resp.pause(length=1)
        resp.play('https://demo.twilio.com/docs/classic.mp3')
        
        # Log and return TwiML
        twiml_response = resp.to_xml()
        logger.info(f"Generated test TwiML: {twiml_response}")
        
        return twiml_response
        
    except Exception as e:
        logger.error(f"Error in test call: {str(e)}", exc_info=True)
        resp = VoiceResponse()
        resp.say('An error occurred during the test.')
        return resp.to_xml()


@router.websocket("/media-stream")
async def media_stream_handler(websocket: WebSocket):
    """Full implementation of Twilio Media Streams protocol with WebRTC integration"""
    connection_id = str(uuid.uuid4())[:8]
    message_count = 0
    audio_chunks = 0
    connected = False
    global manager
    client_id = None
    
    try:
        logger.info(f"[{connection_id}] Media stream connection attempt from {websocket.client.host}")
        
        # Accept the WebSocket connection
        await websocket.accept()
        logger.info(f"[{connection_id}] WebSocket connection accepted")
        
        # Get connection manager from app state if not already initialized
        if not manager:
            logger.info(f"[{connection_id}] Initializing connection manager from app state")
            manager = websocket.app.state.connection_manager
            if not manager:
                logger.error(f"[{connection_id}] Connection manager not found in app state!")
                await websocket.close(code=1011)
                return
        
        # Generate client ID and initialize for connection manager
        client_id = f"twilio_{connection_id}"
        
        # Initialize mock company for Twilio calls
        company_info = {
            "id": "twilio_company",
            "name": "Twilio Caller"
        }
        manager.client_companies[client_id] = company_info
        
        # Connect client to manager
        await manager.connect(websocket, client_id)
        logger.info(f"[{connection_id}] Client {client_id} connected to manager")
        
        # Initialize agent resources
        agent = await manager.agent_manager.get_base_agent(company_info["id"])
        if not agent:
            agent = {
                "id": "twilio_agent",
                "name": "Twilio Assistant"
            }
        
        # Initialize agent resources for this client
        success = await manager.initialize_agent_resources(client_id, company_info["id"], agent)
        if not success:
            logger.error(f"[{connection_id}] Failed to initialize agent resources")
            await websocket.close(code=1011)
            return
        
        # Main message processing loop
        while True:
            message = await websocket.receive()
            message_count += 1
            
            if 'bytes' in message:
                # Binary data (audio chunks)
                audio_data = message['bytes']
                audio_chunks += 1
                
                if audio_chunks == 1 or audio_chunks % 100 == 0:
                    logger.info(f"[{connection_id}] Received audio chunk #{audio_chunks}, size: {len(audio_data)} bytes")
                
                # TODO: In production, you'd send this to your speech-to-text service
                # For now, we'll just log it periodically
                
                # Process through your existing pipeline
                if audio_chunks % 100 == 0:  # Process every 100th chunk as a test
                    # This would be replaced with actual transcription
                    message_data = {
                        "type": "message",
                        "message": f"Processed audio chunk #{audio_chunks}",
                        "source": "twilio"
                    }
                    await manager.process_streaming_message(client_id, message_data)
            
            elif 'text' in message:
                # Parse text messages (control messages)
                text_data = message['text']
                
                try:
                    data = json.loads(text_data)
                    event = data.get('event')
                    
                    if event == 'start':
                        # CRITICAL: Must respond to start event with connected message
                        logger.info(f"[{connection_id}] START event received: {json.dumps(data)}")
                        
                        await websocket.send_text(json.dumps({
                            "event": "connected",
                            "protocol": "websocket",
                            "version": "1.0.0"
                        }))
                        logger.info(f"[{connection_id}] Sent connected response")
                        connected = True
                        
                    elif event == 'media':
                        # Media events contain metadata about the audio
                        if message_count <= 5:
                            logger.info(f"[{connection_id}] Media event: {json.dumps(data)}")
                        
                    elif event == 'stop':
                        logger.info(f"[{connection_id}] STOP event received: {json.dumps(data)}")
                        # Clean exit
                        break
                    
                    elif event == 'mark':
                        logger.info(f"[{connection_id}] Mark event: {json.dumps(data)}")
                        
                    else:
                        logger.info(f"[{connection_id}] Unknown event type: {event}")
                        
                except json.JSONDecodeError:
                    logger.warning(f"[{connection_id}] Non-JSON text received: {text_data[:50]}...")
    
    except Exception as e:
        logger.error(f"[{connection_id}] Error in media stream handler: {str(e)}", exc_info=True)
    finally:
        # Clean up resources
        if client_id and manager:
            logger.info(f"[{connection_id}] Disconnecting client {client_id}")
            await manager.cleanup_agent_resources(client_id)
            manager.disconnect(client_id)
        
        logger.info(f"[{connection_id}] Media stream connection closed after {message_count} messages ({audio_chunks} audio chunks)")

@router.websocket("/stream")
async def handle_stream(websocket: WebSocket):
    """Legacy handler for WebSocket connection for Twilio Media Stream"""
    client_id = None
    connection_id = str(uuid.uuid4())[:8]
    
    logger.info(f"[{connection_id}] Legacy stream connection attempt from {websocket.client.host}")
    
    try:
        # Redirect to the new media-stream handler
        logger.warning(f"[{connection_id}] Legacy /stream endpoint used - redirecting to media-stream handler")
        await media_stream_handler(websocket)
    except Exception as e:
        logger.error(f"[{connection_id}] Error in legacy stream handler: {str(e)}", exc_info=True)
    finally:
        logger.info(f"[{connection_id}] Legacy stream connection closed")

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
        
        # Update active call status
        if CallSid in active_calls:
            active_calls[CallSid]["status"] = CallStatus
            logger.info(f"Updated call status for {CallSid} to {CallStatus}")
            
            # Clean up completed or failed calls
            if CallStatus in ["completed", "failed", "busy", "no-answer"]:
                active_calls[CallSid]["end_time"] = form_data.get('Timestamp')
                active_calls[CallSid]["duration"] = form_data.get('CallDuration')
                logger.info(f"Call {CallSid} ended with status {CallStatus}")
            
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