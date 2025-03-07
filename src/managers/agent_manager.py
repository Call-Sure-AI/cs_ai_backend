from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
import logging
from datetime import datetime
import uuid
import asyncio
from database.models import Agent, Company, Document, Conversation, AgentInteraction
from config.settings import settings
import time
import os
import json
from pathlib import Path
from services.communication.agent_communication import AgentCommunicationService

logger = logging.getLogger(__name__)

class AgentManager:
    def __init__(self, db_session: Session, vector_store):
        self.db = db_session
        self.vector_store = vector_store
        self.agent_cache = {}
        self.company_agents_cache = {}
        self.conversation_cache = {}
        self._initialization_locks = {}


    # managers/agent_manager.py
# Add these methods to your AgentManager class


    def update_company_google_api_settings(db: Session, company_id: str, service_account_json: dict, 
                                          sender_email: str, calendar_id: str) -> bool:
        """
        Update a company's Google API settings in the database
        
        Args:
            db: SQLAlchemy database session
            company_id: UUID string of the company
            service_account_json: Dictionary containing the Google service account JSON
            sender_email: Email address to use as sender for emails/calendar invites
            calendar_id: Google Calendar ID to use for scheduling
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Find the company
            company = db.query(Company).filter_by(id=company_id).first()
            if not company:
                logger.error(f"Company {company_id} not found")
                return False
                
            # Get current settings or initialize empty dict
            settings = company.settings or {}
            
            # Update Google API settings
            if "google_api" not in settings:
                settings["google_api"] = {}
                
            settings["google_api"].update({
                "service_account": service_account_json,
                "sender_email": sender_email,
                "calendar_id": calendar_id
            })
            
            # Save updated settings
            company.settings = settings
            db.commit()
            
            logger.info(f"Updated Google API settings for company {company_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating company Google API settings: {str(e)}")
            db.rollback()
            return False

    def import_service_account_for_company(db: Session, company_id: str, service_account_file_path: str, 
                                        sender_email: str, calendar_id: str) -> bool:
        """
        Import a service account JSON file for a company
        
        Args:
            db: Database session
            company_id: Company UUID string
            service_account_file_path: Path to service account JSON file
            sender_email: Email address to use as sender
            calendar_id: Google Calendar ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Read the service account file
            with open(service_account_file_path, 'r') as f:
                service_account_json = json.load(f)
                
            # Update company settings
            return update_company_google_api_settings(
                db=db,
                company_id=company_id,
                service_account_json=service_account_json,
                sender_email=sender_email,
                calendar_id=calendar_id
            )
            
        except Exception as e:
            logger.error(f"Error importing service account: {str(e)}")
            return False



    async def get_communication_service(self, company_id: str) -> Optional[AgentCommunicationService]:
        """Get or create a communication service for a company"""
        try:
            # Get company settings
            company = self.db.query(Company).filter_by(id=company_id).first()
            if not company:
                logger.error(f"Company {company_id} not found")
                return None
            
            # Check if Google API credentials are configured
            settings = company.settings or {}
            google_config = settings.get("google_api", {})
            
            # Try to get from environment first
            service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
            if not service_account_file:
                # If not in env, check if company has custom service account
                service_account_data = google_config.get("service_account")
                if service_account_data:
                    # Save to a temporary file
                    temp_dir = Path("./temp")
                    temp_dir.mkdir(exist_ok=True)
                    service_account_file = temp_dir / f"{company_id}_service_account.json"
                    with open(service_account_file, "w") as f:
                        json.dump(service_account_data, f)
                    service_account_file = str(service_account_file)
                else:
                    logger.error("Google API service account not configured")
                    return None
            
            # Get sender email and calendar ID
            sender_email = google_config.get("sender_email")
            if not sender_email:
                logger.error("Sender email not configured")
                return None
            
            calendar_id = google_config.get("calendar_id")
            if not calendar_id:
                logger.error("Calendar ID not configured")
                return None
            
            # Create and return the service
            return AgentCommunicationService(
                service_account_json=service_account_file,
                sender_email=sender_email,
                calendar_id=calendar_id
            )
        
        except Exception as e:
            logger.error(f"Error creating communication service: {str(e)}", exc_info=True)
            return None

    async def send_email_from_agent(
        self,
        agent_id: str,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html_body: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an email on behalf of an agent"""
        try:
            # Get agent info
            agent = self.db.query(Agent).filter_by(id=agent_id, active=True).first()
            if not agent:
                return {
                    "status": "error",
                    "message": "Agent not found or inactive"
                }
            
            # Get communication service
            comm_service = await self.get_communication_service(agent.company_id)
            if not comm_service:
                return {
                    "status": "error",
                    "message": "Communication service not available"
                }
            
            # Send email
            result = await comm_service.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                html_body=html_body,
                reply_to=reply_to
            )
            
            # Log the email activity
            try:
                # This could log to a database table for communication history
                logger.info(f"Agent {agent_id} sent email to {', '.join(to)} with subject '{subject}'")
            except Exception as log_error:
                logger.error(f"Error logging email activity: {str(log_error)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending email from agent: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to send email: {str(e)}"
            }

    async def schedule_meeting_from_agent(
        self,
        agent_id: str,
        title: str,
        description: str,
        start_time: datetime,
        duration_minutes: int,
        timezone: str,
        attendees: List[str],
        additional_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Schedule a meeting with Google Meet on behalf of an agent"""
        try:
            # Get agent info
            agent = self.db.query(Agent).filter_by(id=agent_id, active=True).first()
            if not agent:
                return {
                    "status": "error",
                    "message": "Agent not found or inactive"
                }
            
            # Get communication service
            comm_service = await self.get_communication_service(agent.company_id)
            if not comm_service:
                return {
                    "status": "error",
                    "message": "Communication service not available"
                }
            
            # Schedule meeting
            result = await comm_service.combined_schedule_and_invite(
                title=title,
                description=description,
                start_time=start_time,
                duration_minutes=duration_minutes,
                timezone=timezone,
                attendees=attendees,
                additional_message=additional_message
            )
            
            # Log the meeting scheduling activity
            try:
                # This could log to a database table for communication history
                logger.info(f"Agent {agent_id} scheduled meeting '{title}' with {', '.join(attendees)}")
            except Exception as log_error:
                logger.error(f"Error logging meeting activity: {str(log_error)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error scheduling meeting from agent: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to schedule meeting: {str(e)}"
            }


    async def ensure_base_agent(self, company_id: str) -> Optional[Dict[str, Any]]:
        """Ensure base agent exists for company"""
        try:
            base_agent = await self.get_base_agent(company_id)
            if base_agent:
                return base_agent

            # Create default base agent
            agent_id = str(uuid.uuid4())
            base_agent = Agent(
                id=agent_id,
                company_id=company_id,
                name="Base Agent",
                type="base",
                prompt="You are a helpful AI assistant.",
                confidence_threshold=0.0,
                active=True
            )

            self.db.add(base_agent)
            self.db.commit()

            agent_info = {
                "id": agent_id,
                "name": base_agent.name,
                "type": base_agent.type,
                "prompt": base_agent.prompt,
                "confidence_threshold": base_agent.confidence_threshold
            }

            self.agent_cache[agent_id] = agent_info
            return agent_info

        except Exception as e:
            logger.error(f"Error ensuring base agent: {str(e)}")
            return None

    async def initialize_company_agents(self, company_id: str) -> None:
        """Initialize agents with locking and caching"""
        lock = self._initialization_locks.get(company_id)
        if not lock:
            lock = asyncio.Lock()
            self._initialization_locks[company_id] = lock

        async with lock:
            try:
                if company_id in self.company_agents_cache:
                    return

                # Ensure base agent exists
                base_agent = await self.ensure_base_agent(company_id)
                if not base_agent:
                    raise ValueError("Failed to create base agent")

                # Get all active agents
                agents = self.db.query(Agent).filter_by(
                    company_id=company_id,
                    active=True
                ).all()

                self.company_agents_cache[company_id] = []

                for agent in agents:
                    agent_info = {
                        "id": agent.id,
                        "name": agent.name,
                        "type": agent.type,
                        "prompt": agent.prompt,
                        "confidence_threshold": agent.confidence_threshold,
                        "additional_context": agent.additional_context
                    }
                    
                    self.agent_cache[agent.id] = agent_info
                    self.company_agents_cache[company_id].append(agent.id)

                    # Load documents if any exist
                    documents = self.db.query(Document).filter_by(agent_id=agent.id).all()
                    if documents:
                        docs_data = [{
                            'id': doc.id,
                            'content': doc.content,
                            'metadata': {
                                'agent_id': agent.id,
                                'file_type': doc.file_type,
                                'original_filename': doc.original_filename,
                                'doc_type': doc.type
                            }
                        } for doc in documents]
                        
                        await self.vector_store.load_documents(
                            company_id=company_id,
                            agent_id=agent.id,
                            documents=docs_data
                        )

                logger.info(f"Initialized {len(agents)} agents for company {company_id}")

            except Exception as e:
                logger.error(f"Error initializing agents: {str(e)}")
                self.agent_cache.pop(company_id, None)
                self.company_agents_cache.pop(company_id, None)
                raise

    async def get_company_agents(self, company_id: str) -> List[Dict[str, Any]]:
        """Get all agents for company"""
        if company_id not in self.company_agents_cache:
            await self.initialize_company_agents(company_id)

        return [
            self.agent_cache[agent_id]
            for agent_id in self.company_agents_cache.get(company_id, [])
        ]

    async def get_base_agent(self, company_id: str) -> Optional[Dict[str, Any]]:
        """Get base agent with caching"""
        try:
            # Check cache first
            if company_id in self.company_agents_cache:
                for agent_id in self.company_agents_cache[company_id]:
                    agent = self.agent_cache.get(agent_id)
                    if agent and agent['type'] == 'base':
                        return agent

            # Query database
            base_agent = self.db.query(Agent).filter_by(
                company_id=company_id,
                type='base',
                active=True
            ).first()

            if base_agent:
                agent_info = {
                    "id": base_agent.id,
                    "name": base_agent.name,
                    "type": base_agent.type,
                    "prompt": base_agent.prompt,
                    "confidence_threshold": base_agent.confidence_threshold,
                    "additional_context": base_agent.additional_context
                }
                
                self.agent_cache[base_agent.id] = agent_info
                if company_id not in self.company_agents_cache:
                    self.company_agents_cache[company_id] = []
                self.company_agents_cache[company_id].append(base_agent.id)
                
                return agent_info

            return None

        except Exception as e:
            logger.error(f"Error getting base agent: {str(e)}")
            return None

    async def create_conversation(
        self,
        company_id: str,
        client_id: str
    ) -> Optional[Dict[str, Any]]:
        """Create conversation with proper error handling"""
        try:
            # Ensure base agent exists
            base_agent = await self.ensure_base_agent(company_id)
            if not base_agent:
                raise ValueError("No base agent available")

            conversation_id = str(uuid.uuid4())
            conversation = Conversation(
                id=conversation_id,
                customer_id=client_id,
                company_id=company_id,
                current_agent_id=base_agent['id'],
                meta_data={
                    "created_at": datetime.utcnow().isoformat(),
                    "client_info": {"client_id": client_id}
                }
            )

            self.db.add(conversation)
            self.db.commit()

            conv_info = {
                "id": conversation_id,
                "company_id": company_id,
                "customer_id": client_id,
                "current_agent_id": base_agent['id'],
                "meta_data": conversation.meta_data
            }

            self.conversation_cache[conversation_id] = conv_info
            return conv_info

        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            self.db.rollback()
            return None

    async def find_best_agent(
        self,
        company_id: str,
        query: str,
        current_agent_id: Optional[str] = None
    ) -> Tuple[Optional[str], float]:
        """Find best agent using pre-computed embeddings"""
        try:
            if company_id not in self.company_agents_cache:
                await self.initialize_company_agents(company_id)

            # Get query embedding from cache or compute
            query_embedding = await self.vector_store.get_query_embedding(query)
            
            # Search with embedding
            results = await self.vector_store.search(
                company_id=company_id,
                query_embedding=query_embedding,
                current_agent_id=current_agent_id
            )

            if not results:
                base_agent = await self.get_base_agent(company_id)
                return base_agent['id'] if base_agent else None, 0.0

            best_result = results[0]
            return best_result['agent_id'], best_result['score']

        except Exception as e:
            logger.error(f"Error finding best agent: {str(e)}")
            if current_agent_id:
                return current_agent_id, 0.0
            base_agent = await self.get_base_agent(company_id)
            return base_agent['id'] if base_agent else None, 0.0

    async def update_conversation(
        self,
        conversation_id: str,
        user_message: str,
        ai_response: str,
        agent_id: str,
        confidence_score: float = 0.0,
        tokens_used: Optional[int] = None,
        was_successful: bool = True,
        previous_agent_id: Optional[str] = None
    ) -> bool:
        try:
            response_time = time.time()  # Add response time tracking
            
            interaction = AgentInteraction(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                agent_id=agent_id,
                query=user_message,
                response=ai_response,
                confidence_score=confidence_score, 
                tokens_used=tokens_used,
                response_time=response_time,
                was_successful=was_successful,
                previous_agent_id=previous_agent_id,
                created_at=datetime.utcnow()
            )
            
            self.db.add(interaction)

            conversation = self.db.query(Conversation).filter_by(id=conversation_id).first()
            if conversation:
                conversation.current_agent_id = agent_id
                conversation.updated_at = datetime.utcnow()
                
                if conversation_id in self.conversation_cache:
                    self.conversation_cache[conversation_id].update({
                        "current_agent_id": agent_id,
                        "updated_at": conversation.updated_at.isoformat()
                    })

            self.db.commit()
            return True

        except Exception as e:
            logger.error(f"Error updating conversation: {str(e)}")
            self.db.rollback()
            return False
    
    async def get_conversation_context(
        self,
        conversation_id: str,
        limit: int = 5
    ) -> List[Dict[str, str]]:
        """Get recent conversation history"""
        try:
            interactions = self.db.query(AgentInteraction).filter_by(
                conversation_id=conversation_id
            ).order_by(
                AgentInteraction.created_at.desc()
            ).limit(limit).all()

            context = []
            for interaction in reversed(interactions):
                context.extend([
                    {"role": "user", "content": interaction.query},
                    {"role": "assistant", "content": interaction.response}
                ])

            return context

        except Exception as e:
            logger.error(f"Error getting conversation context: {str(e)}")
            return []

    async def cleanup_inactive_agents(self, days: int = 30) -> None:
        """Cleanup inactive agents and their data"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            inactive_agents = self.db.query(Agent).filter(
                Agent.updated_at < cutoff,
                Agent.type != 'base'
            ).all()

            for agent in inactive_agents:
                # Delete from vector store
                await self.vector_store.delete_agent_data(agent.company_id, agent.id)
                
                # Clear caches
                self.agent_cache.pop(agent.id, None)
                if agent.company_id in self.company_agents_cache:
                    self.company_agents_cache[agent.company_id] = [
                        aid for aid in self.company_agents_cache[agent.company_id]
                        if aid != agent.id
                    ]

                # Delete from DB
                self.db.delete(agent)

            self.db.commit()
            logger.info(f"Cleaned up {len(inactive_agents)} inactive agents")

        except Exception as e:
            logger.error(f"Error cleaning up agents: {str(e)}")
            self.db.rollback()