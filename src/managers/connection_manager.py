# managers/connection_manager.py
from typing import Dict, Optional, List
import logging
import asyncio
import time
import base64
from datetime import datetime
from fastapi import WebSocket
from contextlib import asynccontextmanager
from database.models import Company, Conversation, Agent, Document
from managers.agent_manager import AgentManager
from services.vector_store.qdrant_service import QdrantService
from services.rag.rag_service import RAGService
from sqlalchemy.orm import Session
import json
from uuid import UUID
from json import JSONEncoder

logger = logging.getLogger(__name__)

class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)
    
class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

class ConnectionManager:
    def __init__(self,db_session: Session, vector_store=None):
        # Basic WebSocket management
        self.db = db_session
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_companies: Dict[str, Company] = {}
        self.client_conversations: Dict[str, Conversation] = {}
        
        # Initialize vector store if not provided
        self.vector_store = vector_store
        if self.vector_store is None:
            self.vector_store = QdrantService()
        
        self.agent_manager = AgentManager(db_session, self.vector_store)
        self.rag_service = RAGService(self.vector_store)    
        
        
        # Connection monitoring
        self.connection_times: Dict[str, datetime] = {}
        self.message_counts: Dict[str, int] = {}
        self.active_agents: Dict[str, str] = {}  # client_id -> agent_id
        # Add response caching
        self._response_cache = {}
        self._cache_size = 1000
        self._cache_ttl = 300  # 5 minutes
        
        # Add request deduplication
        self._recent_requests = {}
        self._request_ttl = 3  # 3 seconds
        self.agent_resources = {}
        
        self.json_encoder = UUIDEncoder()
        
        # Add concurrent processing limits
        self._processing_semaphore = asyncio.Semaphore(10)
        
        self._request_queue = asyncio.Queue()
        self._batch_size = 5
        self._batch_timeout = 0.1  # 100ms
        self.text_buffer = ""
        self.buffer_lock = asyncio.Lock()
        
    
        self._connection_states = {}
        self._state_lock = asyncio.Lock()
    
        
        
        # Start batch processor
        asyncio.create_task(self._process_batches())


    async def send_json(self, websocket: WebSocket, data: dict) -> bool:
        """Send JSON data with improved error handling and connection validation"""
        try:
            # First check if websocket is already closed
            if self.websocket_is_closed(websocket):
                logger.warning("Attempted to send to closed websocket")
                return False
                
            # Convert to JSON string with UUID handling
            json_str = json.dumps(data, cls=UUIDEncoder)
            
            # Send with timeout to prevent hanging
            await asyncio.wait_for(
                websocket.send_text(json_str),
                timeout=2.0  # Reduce timeout to 2 seconds
            )
            return True
            
        except asyncio.TimeoutError:
            logger.error("Timeout sending JSON message")
            return False
        except Exception as e:
            if "disconnected" in str(e).lower() or "closed" in str(e).lower():
                logger.warning("Client disconnected during send operation")
            else:
                logger.error(f"Error sending JSON: {str(e)}", exc_info=True)
            return False


    async def _process_batches(self):
        while True:
            batch = []
            try:
                request = await self._request_queue.get()
                batch.append(request)
                
                timeout = self._batch_timeout
                while len(batch) < self._batch_size:
                    try:
                        request = await asyncio.wait_for(
                            self._request_queue.get(),
                            timeout=timeout
                        )
                        batch.append(request)
                    except asyncio.TimeoutError:
                        break
                
                responses = await asyncio.gather(
                    *[self._process_single_request(req) for req in batch],
                    return_exceptions=True
                )
                
                for req, res in zip(batch, responses):
                    if not isinstance(res, Exception):
                        await self._send_response(
                            req['client_id'], 
                            res, 
                            req.get('metadata', {})
                        )
                    
            except Exception as e:
                logger.error(f"Batch processing error: {str(e)}")

     
    async def initialize_agent_resources(self, client_id: str, company_id: str, agent_info: dict):
        """Initialize agent resources with proper embedding handling"""
        try:
            # websocket = self.active_connections.get(client_id)
            # if not websocket or self.websocket_is_closed(websocket):
            #     logger.warning(f"Client {client_id} disconnected during initialization")
            #     return False
            
            # Create RAG service instance
            rag_service = RAGService(self.vector_store)
            
            # # First verify that embeddings exist and are accessible
            # embeddings_exist = await rag_service.verify_embeddings(
            #     company_id=company_id,
            #     agent_id=agent_info['id']
            # )
            
            # if not embeddings_exist:
            #     # If embeddings don't exist, load and add documents
            #     documents = await self.load_agent_documents(company_id, agent_info['id'])
            #     if documents:
            #         success = await rag_service.add_documents(
            #             company_id=company_id,
            #             documents=documents,
            #             agent_id=agent_info['id']
            #         )
            #         if not success:
            #             raise ValueError("Failed to add documents to vector store")
            
            # # Create chain with existing embeddings
            chain = await rag_service.create_qa_chain(
                company_id=company_id,
                agent_id=agent_info['id']
            )
            
            self.agent_resources[client_id] = {
                "rag_service": rag_service,
                "chain": chain,
                "agent_info": agent_info
            }
            
            
            logger.info(f"Successfully initialized agent resources for {agent_info['id']} and agent resource {self.agent_resources[client_id]}")
            return True

        except Exception as e:
            logger.error(f"Error initializing agent resources: {str(e)}")
            return False
        
    async def load_agent_documents(self, company_id: str, agent_id: str) -> List[Dict]:
        """Load agent's documents from database"""
        try:
            documents = self.db.query(Document).filter_by(
                agent_id=agent_id,
                company_id=company_id
            ).all()
            
            return [{
                'id': doc.id,
                'content': doc.content,
                'metadata': {
                    'agent_id': doc.agent_id,
                    'file_type': doc.file_type,
                    'original_filename': doc.original_filename,
                    'doc_type': doc.type
                }
            } for doc in documents]

        except Exception as e:
            logger.error(f"Error loading agent documents: {str(e)}")
            return []
    
    async def cleanup_agent_resources(self, client_id: str):
        """Clean up resources with state tracking"""
        try:
            if client_id in self.agent_resources:
                self.agent_resources.pop(client_id)
                
            if client_id in self._connection_states:
                self._connection_states[client_id]["initialized"] = False
                
            logger.info(f"Cleaned up agent resources for client {client_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up agent resources: {str(e)}")
    
    def initialize_agent_manager(self, db_session):
        if not self.agent_manager:
            vector_store = QdrantService()
            self.agent_manager = AgentManager(db_session, self.vector_store)
            logger.info("Agent manager initialized")
    
    
    async def initialize_client(self, client_id: str) -> None:
        try:
            company_info = self.client_companies.get(client_id)
            if not company_info:
                return

            if not self.agent_manager:
                raise ValueError("Agent manager not initialized")
            
            await self.agent_manager.initialize_company_agents(company_info['id'])
            
            # Send available agents list
            websocket = self.active_connections.get(client_id)
            if websocket and not self.websocket_is_closed(websocket):
                agents = await self.agent_manager.get_company_agents(company_info['id'])
                data = {
                    "type": "agents",
                    "data": agents
                }
                await self.send_json(websocket, data)
                # await websocket.send_json({
                #     "type": "agents",
                #     "data": agents
                # })

        except Exception as e:
            logger.error(f"Error initializing client: {str(e)}")
            await self.handle_error(client_id, str(e))
    
    
    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Initialize connection with proper state tracking"""
        async with self._state_lock:
            try:
                # Add connection tracking
                self._connection_states[client_id] = {
                    "connected": True,
                    "initialized": False,
                    "last_activity": datetime.utcnow()
                }
                
                self.active_connections[client_id] = websocket
                self.message_counts[client_id] = 0
                self.connection_times[client_id] = datetime.utcnow()
                
                logger.info(f"Client {client_id} connected")
                
            except Exception as e:
                logger.error(f"Connection error: {str(e)}")
                self._connection_states[client_id] = {"connected": False}
                raise
    
    def disconnect(self, client_id: str) -> None:
        """Handle disconnection with proper state cleanup"""
        try:
            websocket = self.active_connections.get(client_id)
            if websocket and not self.websocket_is_closed(websocket):
                asyncio.create_task(websocket.close())
            
            # Update connection state
            if client_id in self._connection_states:
                self._connection_states[client_id]["connected"] = False
            
            # Remove from active connections
            self.active_connections.pop(client_id, None)
            self.client_companies.pop(client_id, None)
            self.client_conversations.pop(client_id, None)
            self.message_counts.pop(client_id, None)
            self.active_agents.pop(client_id, None)
            self.connection_times.pop(client_id, None)
            
            logger.info(f"Client {client_id} disconnected")
            
        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}")
    
    async def close_all_connections(self):
        try:
            close_tasks = []
            for client_id, websocket in self.active_connections.items():
                if not websocket.closed:
                    try:
                        await websocket.send_json({
                            "type": "system",
                            "message": "Server shutting down"
                        })
                        close_tasks.append(websocket.close())
                    except Exception as e:
                        logger.error(f"Error closing connection {client_id}: {str(e)}")
            
            if close_tasks:
                await asyncio.gather(*close_tasks, return_exceptions=True)
                
            self.active_connections.clear()
            self.client_companies.clear()
            self.client_conversations.clear()
            
        except Exception as e:
            logger.error(f"Error closing connections: {str(e)}")

    async def _get_or_create_conversation(self, company_id: str, client_id: str) -> Optional[Dict]:
        try:
            conversation = self.client_conversations.get(client_id)
            if conversation:
                return conversation

            conversation = await self.agent_manager.create_conversation(
                company_id, 
                client_id
            )
            if not conversation:
                raise ValueError("Failed to create conversation")
                
            self.client_conversations[client_id] = conversation
            return conversation
            
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            raise

    
    async def process_streaming_message_with_speech(self, client_id: str, message_data: dict):
        """Process incoming message with speech-to-text/text-to-speech support for Twilio"""
        start_time = time.time()
        msg_id = str(time.time())  # Generate a unique message ID for this response
        chunk_number = 0
        accumulated_text = ""
        
        try:
            websocket = self.active_connections.get(client_id)
            if not websocket or self.websocket_is_closed(websocket):
                logger.warning(f"Dropping message for disconnected client {client_id}")
                return

            agent_resources = self.agent_resources.get(client_id)
            logger.info(f"Agent resources for {client_id} are {agent_resources}")

            if not agent_resources:
                raise ValueError("Agent resources not initialized")

            company_info = self.client_companies.get(client_id)
            logger.info(f"Company info for {client_id} is {company_info}")

            if not company_info or not websocket:
                raise ValueError("Invalid connection state")

            # Fetch conversation context
            conversation = self.client_conversations.get(client_id)
            if not conversation:
                conversation = await self.agent_manager.create_conversation(company_info['id'], client_id)
                logger.info(f"Created conversation {conversation}") 
            if not conversation:
                raise ValueError("Failed to create conversation")
            
            self.client_conversations[client_id] = conversation
            
            context = await self.agent_manager.get_conversation_context(conversation['id'])

            # Get RAG Service
            chain = agent_resources['chain']
            rag_service = agent_resources['rag_service']

            # Check if this is a Twilio client
            is_twilio_client = client_id.startswith('twilio_')

            # Stream Response Token-by-Token
            async for token in rag_service.get_answer_with_chain(
                chain=chain,
                question=message_data.get('message', ''),
                conversation_context=context
            ):
                chunk_number += 1
                
                # For regular WebSocket clients, send streaming chunks
                await self.send_json(websocket, {
                    "type": "stream_chunk",
                    "text_content": token,
                    "audio_content": None,  # No audio yet
                    "chunk_number": chunk_number,
                    "msg_id": msg_id
                })
                
                # Accumulate text for speech synthesis (for Twilio)
                accumulated_text += token
                
                # Check if we have a complete sentence to send as speech for Twilio
                if is_twilio_client and any(char in accumulated_text for char in ['.', '!', '?', '\n']):
                    # This will be handled by the Twilio module
                    await self.handle_twilio_speech(client_id, accumulated_text)
                    accumulated_text = ""  # Reset after sending
                
                logger.info(f"Chunk {chunk_number} sent to client {client_id} and msg_id {msg_id}, content: {token}")

            # Send any remaining text
            if is_twilio_client and accumulated_text.strip():
                await self.handle_twilio_speech(client_id, accumulated_text)

            # Send end of stream message
            await self.send_json(websocket, {
                "type": "stream_end",
                "msg_id": msg_id
            })
            
            logger.info(f"Final response sent to client {client_id}")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.handle_error(client_id, str(e))
        finally:
            logger.info(f"Processing time: {time.time() - start_time:.3f}s")

    async def handle_twilio_speech(self, client_id: str, text: str):
        """Handle speech synthesis for Twilio clients"""
        try:
            # This method will be called by the connection manager
            # Reference to the handle_ai_response in the Twilio module
            from routes.twilio_handlers import handle_ai_response
            await handle_ai_response(client_id, text)
        except Exception as e:
            logger.error(f"Error in handle_twilio_speech: {str(e)}")
    
    
    async def process_streaming_message(self, client_id: str, message_data: dict):
        """Process incoming WebSocket messages and stream responses with msg_id tracking."""
        start_time = time.time()
        msg_id = str(time.time())  # Generate a unique message ID for this response
        chunk_number = 0
        
        try:
            websocket = self.active_connections.get(client_id)
            if not websocket or self.websocket_is_closed(websocket):
                logger.warning(f"Dropping message for disconnected client {client_id}")
                return

            agent_resources = self.agent_resources.get(client_id)
            logger.info(f"Agent resources for {client_id} are {agent_resources}")

            if not agent_resources:
                raise ValueError("Agent resources not initialized")

            company_info = self.client_companies.get(client_id)
            logger.info(f"Company info for {client_id} is {company_info}")

            if not company_info or not websocket:
                raise ValueError("Invalid connection state")

            # Fetch conversation context
            conversation = self.client_conversations.get(client_id)
            if not conversation:
                conversation = await self.agent_manager.create_conversation(company_info['id'], client_id)
                logger.info(f"Created conversation {conversation}") 
            if not conversation:
                raise ValueError("Failed to create conversation")
            
            self.client_conversations[client_id] = conversation
            
            context = await self.agent_manager.get_conversation_context(conversation['id'])

            # Get RAG Service
            chain = agent_resources['chain']
            rag_service = agent_resources['rag_service']

            # Stream Response Token-by-Token
            async for token in rag_service.get_answer_with_chain(
                chain=chain,
                question=message_data.get('message', ''),
                conversation_context=context
            ):
                chunk_number += 1
                if self.websocket_is_closed(websocket):
                    logger.warning(f"Websocket closed during streaming for client {client_id}")
                    break
                    
                success = await self.send_json(websocket, {
                    "type": "stream_chunk",
                    "text_content": token,
                    "audio_content": None,
                    "chunk_number": chunk_number,
                    "msg_id": msg_id
                })
                
                # If sending failed, stop streaming
                if not success:
                    logger.warning(f"Failed to send chunk {chunk_number} to client {client_id}")
                    break
                    
                logger.info(f"Chunk {chunk_number} sent to client {client_id} and msg_id {msg_id}, content: {token}")

            # Send end of stream message
            await self.send_json(websocket, {
                "type": "stream_end",
                "msg_id": msg_id
            })
            
            logger.info(f"Final response sent to client {client_id}")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.handle_error(client_id, str(e))
        finally:
            logger.info(f"Processing time: {time.time() - start_time:.3f}s")
    
    
    async def send_welcome_message(self, client_id: str):
        try:
            websocket = self.active_connections.get(client_id)
            company_info = self.client_companies.get(client_id)
            if not websocket or websocket.closed or not company_info:
                return

            welcome_msg = f"Welcome to {company_info['name']}!"
            agent_id = None

            if self.agent_manager:
                base_agent = await self.agent_manager.get_base_agent(company_info['id'])
                if base_agent:
                    self.active_agents[client_id] = base_agent['id']
                    agent_id = base_agent['id']

            await websocket.send_text(self.json_encoder.encode({
                "type": "system",
                "message": welcome_msg,
                "metadata": {
                    "company_name": company_info['name'],
                    "agent_id": agent_id
                }
            }))

        except Exception as e:
            logger.error(f"Error sending welcome: {str(e)}")
            await self.handle_error(client_id, str(e))
    
    async def handle_error(self, client_id: str, error_message: str):
        try:
            websocket = self.active_connections.get(client_id)
            if websocket and not websocket.closed:
                await websocket.send_json({
                    "type": "error",
                    "error": {
                        "message": error_message,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
        except Exception as e:
            logger.error(f"Error handling error: {str(e)}")
    
    async def handle_connection_error(self, websocket: WebSocket, client_id: str):
        try:
            if not websocket._client_state.closed:
                await websocket.close(code=1011)
            self.disconnect(client_id)
        except Exception as e:
            logger.error(f"Error handling connection error: {str(e)}")

    async def _send_response(self, client_id: str, content: str, agent_id: str, 
                           confidence: float, require_audio: bool):
        """Helper method to send response"""
        websocket = self.active_connections.get(client_id)
        if websocket:
            if require_audio:
                await websocket.send_json({
                    "type": "text",
                    "response": content,
                    "metadata": {
                        "agent_id": agent_id,
                        "confidence": confidence
                    }
                })
                await self.audio_service.stream_audio_response(
                    websocket,
                    content,
                    metadata={
                        "agent_id": agent_id,
                        "confidence": confidence
                    }
                )
            else:
                await websocket.send_json({
                    "type": "text",
                    "response": content,
                    "metadata": {
                        "agent_id": agent_id,
                        "confidence": confidence
                    }
                })
    
    
    
    
    async def handle_error(self, client_id: str, error_message: str):
        try:
            websocket = self.active_connections.get(client_id)
            if websocket and not self.websocket_is_closed(websocket):
                await websocket.send_json({
                    "type": "error",
                    "error": {
                        "message": error_message,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
        except Exception as e:
            logger.error(f"Error handling error: {str(e)}")
            
    @staticmethod
    def websocket_is_closed(websocket: WebSocket) -> bool:
        """Check if websocket is closed with better error handling"""
        try:
            return (
                websocket.client_state.name == "DISCONNECTED" or
                websocket.application_state.name == "DISCONNECTED" or
                getattr(websocket, '_closed', False)
            )
        except (AttributeError, Exception):
            # If we can't check the state or any error occurs, assume it's closed for safety
            return True