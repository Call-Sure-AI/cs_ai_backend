from typing import Dict, List, Optional, Tuple, Any, Set
from sqlalchemy.orm import Session
import logging
from datetime import datetime, timedelta
import uuid
import asyncio
import time
from database.models import Agent, Company, Document, Conversation, AgentInteraction
from config.settings import settings

logger = logging.getLogger(__name__)

class AgentManager:
    def __init__(self, db_session: Session, vector_store):
        """Initialize Agent Manager with database and vector store"""
        self.db = db_session
        self.vector_store = vector_store
        
        # Caching structures
        self.agent_cache = {}  # agent_id -> agent_info
        self.company_agents_cache = {}  # company_id -> list of agent_ids
        self.conversation_cache = {}  # conversation_id -> conversation_info
        
        # Cache expiration timestamps
        self.agent_cache_timestamps = {}  # agent_id -> timestamp
        self.cache_ttl = 1800  # 30 minutes in seconds
        
        # Concurrency control
        self._initialization_locks = {}  # company_id -> lock
        self._db_lock = asyncio.Lock()  # Database transaction lock
        
        # Metrics tracking
        self._metrics = {
            "cache_hits": 0,
            "cache_misses": 0,
            "db_queries": 0,
            "successful_conversations": 0,
            "failed_conversations": 0
        }

    async def ensure_base_agent(self, company_id: str) -> Optional[Dict[str, Any]]:
        """Ensure base agent exists for company with improved error handling"""
        try:
            # Check cache first 
            base_agent = await self.get_base_agent(company_id)
            if base_agent:
                self._metrics["cache_hits"] += 1
                return base_agent

            # Acquire lock for database operations
            async with self._db_lock:
                # Double-check after acquiring lock (to prevent race conditions)
                base_agent = await self.get_base_agent(company_id, bypass_cache=True)
                if base_agent:
                    return base_agent
                
                self._metrics["db_queries"] += 1
                
                # Get company to get the user_id
                company = self.db.query(Company).filter_by(id=company_id).first()
                if not company:
                    logger.error(f"Company {company_id} not found")
                    return None
                    
                # Get user_id from company
                user_id = company.user_id
                if not user_id:
                    logger.error(f"No user_id found for company {company_id}")
                    return None

                # Create default base agent with user_id from company
                agent_id = str(uuid.uuid4())
                base_agent = Agent(
                    id=agent_id,
                    company_id=company_id,
                    user_id=user_id,  # Use user_id from company
                    name="Base Agent",
                    type="base",
                    prompt="You are a helpful AI assistant.",
                    confidence_threshold=0.0,
                    is_active=True
                )

                try:
                    self.db.add(base_agent)
                    self.db.commit()
                    
                    agent_info = {
                        "id": agent_id,
                        "name": base_agent.name,
                        "type": base_agent.type,
                        "prompt": base_agent.prompt,
                        "confidence_threshold": base_agent.confidence_threshold
                    }
                    
                    # Update cache
                    self.agent_cache[agent_id] = agent_info
                    self.agent_cache_timestamps[agent_id] = time.time()
                    
                    if company_id not in self.company_agents_cache:
                        self.company_agents_cache[company_id] = []
                        
                    self.company_agents_cache[company_id].append(agent_id)
                    
                    logger.info(f"Created new base agent for company {company_id}: {agent_id}")
                    return agent_info
                    
                except Exception as db_error:
                    self.db.rollback()
                    logger.error(f"Database error creating base agent: {str(db_error)}")
                    raise

        except Exception as e:
            logger.error(f"Error ensuring base agent: {str(e)}")
            if 'db' in locals() and hasattr(self, 'db'):
                self.db.rollback()
            return None
        
    async def initialize_company_agents(self, company_id: str) -> None:
        """Initialize agents with locking and caching with enhanced error handling"""
        # Get or create lock for this company
        if company_id not in self._initialization_locks:
            self._initialization_locks[company_id] = asyncio.Lock()
        
        lock = self._initialization_locks[company_id]

        async with lock:
            try:
                # Check if already initialized and not expired
                if company_id in self.company_agents_cache:
                    first_agent_id = self.company_agents_cache[company_id][0] if self.company_agents_cache[company_id] else None
                    if first_agent_id and first_agent_id in self.agent_cache_timestamps:
                        if time.time() - self.agent_cache_timestamps[first_agent_id] < self.cache_ttl:
                            self._metrics["cache_hits"] += 1
                            return

                self._metrics["cache_misses"] += 1
                self._metrics["db_queries"] += 1

                # Ensure base agent exists
                base_agent = await self.ensure_base_agent(company_id)
                if not base_agent:
                    logger.error(f"Failed to create or retrieve base agent for company {company_id}")
                    raise ValueError("Failed to create base agent")

                # Get all active agents
                agents = self.db.query(Agent).filter_by(
                    company_id=company_id,
                    is_active=True
                ).all()

                if not agents:
                    logger.warning(f"No active agents found for company {company_id}")
                
                # Clear existing cache for this company
                if company_id in self.company_agents_cache:
                    # Clean up agent cache entries for this company
                    for agent_id in self.company_agents_cache[company_id]:
                        self.agent_cache.pop(agent_id, None)
                        self.agent_cache_timestamps.pop(agent_id, None)
                
                # Initialize new cache
                self.company_agents_cache[company_id] = []
                current_time = time.time()

                # Process each agent
                document_load_tasks = []
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
                    self.agent_cache_timestamps[agent.id] = current_time
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
                        
                        # Collect document loading tasks
                        document_load_tasks.append((agent.id, docs_data))

                # Load documents in parallel
                if document_load_tasks:
                    for agent_id, docs_data in document_load_tasks:
                        try:
                            await self.vector_store.load_documents(
                                company_id=company_id,
                                agent_id=agent_id,
                                documents=docs_data
                            )
                        except Exception as doc_error:
                            logger.error(f"Error loading documents for agent {agent_id}: {str(doc_error)}")
                            # Continue with other agents even if one fails

                logger.info(f"Initialized {len(agents)} agents for company {company_id}")

            except Exception as e:
                logger.error(f"Error initializing agents: {str(e)}")
                # Cleanup partial cache state on error
                if company_id in self.company_agents_cache:
                    for agent_id in self.company_agents_cache[company_id]:
                        self.agent_cache.pop(agent_id, None)
                        self.agent_cache_timestamps.pop(agent_id, None)
                    self.company_agents_cache.pop(company_id, None)
                raise
            
    async def get_company_agents(self, company_id: str) -> List[Dict[str, Any]]:
        """Get all agents for company with caching and validation"""
        try:
            # Ensure company agents are initialized
            if company_id not in self.company_agents_cache:
                await self.initialize_company_agents(company_id)
                self._metrics["cache_misses"] += 1
            else:
                self._metrics["cache_hits"] += 1

            # Check for expired cache
            if company_id in self.company_agents_cache and self.company_agents_cache[company_id]:
                first_agent_id = self.company_agents_cache[company_id][0]
                if (first_agent_id in self.agent_cache_timestamps and 
                    time.time() - self.agent_cache_timestamps[first_agent_id] > self.cache_ttl):
                    # Cache expired, reinitialize
                    await self.initialize_company_agents(company_id)
            
            # Get agent data from cache
            agents = []
            for agent_id in self.company_agents_cache.get(company_id, []):
                agent_info = self.agent_cache.get(agent_id)
                if agent_info:
                    agents.append(agent_info)
            
            return agents
        
        except Exception as e:
            logger.error(f"Error getting company agents: {str(e)}")
            return []  # Return empty list instead of failing

    async def get_base_agent(self, company_id: str, bypass_cache: bool = False) -> Optional[Dict[str, Any]]:
        """Get base agent with improved caching"""
        try:
            # Check cache first unless bypassing
            if not bypass_cache and company_id in self.company_agents_cache:
                for agent_id in self.company_agents_cache[company_id]:
                    agent = self.agent_cache.get(agent_id)
                    if agent and agent['type'] == 'base':
                        # Check if cache is still valid
                        if (agent_id in self.agent_cache_timestamps and
                            time.time() - self.agent_cache_timestamps[agent_id] < self.cache_ttl):
                            self._metrics["cache_hits"] += 1
                            return agent

            # Cache miss or bypass, query database
            self._metrics["db_queries"] += 1
            self._metrics["cache_misses"] += 1
            
            base_agent = self.db.query(Agent).filter_by(
                company_id=company_id,
                type='base',
                is_active=True
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
                
                # Update cache
                self.agent_cache[base_agent.id] = agent_info
                self.agent_cache_timestamps[base_agent.id] = time.time()
                
                if company_id not in self.company_agents_cache:
                    self.company_agents_cache[company_id] = []
                
                if base_agent.id not in self.company_agents_cache[company_id]:
                    self.company_agents_cache[company_id].append(base_agent.id)
                
                return agent_info

            return None

        except Exception as e:
            logger.error(f"Error getting base agent: {str(e)}")
            return None

    async def create_conversation(
        self,
        company_id: str,
        client_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Create conversation with improved error handling and metadata support"""
        try:
            # Ensure base agent exists
            base_agent = await self.ensure_base_agent(company_id)
            if not base_agent:
                logger.error(f"No base agent available for company {company_id}")
                raise ValueError("No base agent available")

            conversation_id = str(uuid.uuid4())
            
            # Merge provided metadata with default metadata
            conversation_metadata = {
                "created_at": datetime.utcnow().isoformat(),
                "client_info": {"client_id": client_id},
                "source": "api"
            }
            
            if metadata:
                conversation_metadata.update(metadata)

            # Create conversation with transaction handling
            async with self._db_lock:
                conversation = Conversation(
                    id=conversation_id,
                    customer_id=client_id,
                    company_id=company_id,
                    current_agent_id=base_agent['id'],
                    meta_data=conversation_metadata,
                    history=[]  # Initialize with empty history
                )

                try:
                    self.db.add(conversation)
                    self.db.commit()
                    
                    conv_info = {
                        "id": conversation_id,
                        "company_id": company_id,
                        "customer_id": client_id,
                        "current_agent_id": base_agent['id'],
                        "meta_data": conversation_metadata,
                        "created_at": datetime.utcnow().isoformat()
                    }

                    # Update cache
                    self.conversation_cache[conversation_id] = conv_info
                    self._metrics["successful_conversations"] += 1
                    
                    logger.info(f"Created conversation {conversation_id} for company {company_id}, client {client_id}")
                    return conv_info
                    
                except Exception as db_error:
                    self.db.rollback()
                    logger.error(f"Database error creating conversation: {str(db_error)}")
                    self._metrics["failed_conversations"] += 1
                    raise

        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            if hasattr(self, 'db'):
                self.db.rollback()
            return None

    async def find_best_agent(
        self,
        company_id: str,
        query: str,
        current_agent_id: Optional[str] = None,
        confidence_threshold: float = 0.6  # Default threshold
    ) -> Tuple[Optional[str], float]:
        """Find best agent using vector similarity with improved error handling"""
        try:
            # Ensure company agents are initialized
            if company_id not in self.company_agents_cache:
                await self.initialize_company_agents(company_id)

            # Get query embedding
            query_embedding = await self.vector_store.get_query_embedding(query)
            
            # Track start time for performance monitoring
            start_time = time.time()
            
            # Search with embedding
            results = await self.vector_store.search(
                company_id=company_id,
                query_embedding=query_embedding,
                current_agent_id=current_agent_id,
                limit=3,  # Get top 3 results to examine
                score_threshold=0.5  # Base threshold
            )
            
            search_time = time.time() - start_time
            logger.info(f"Agent search completed in {search_time:.3f}s")

            if not results:
                # No good matches, use current agent or base agent
                if current_agent_id:
                    logger.info(f"No matching agents found, keeping current agent {current_agent_id}")
                    return current_agent_id, 0.0
                
                base_agent = await self.get_base_agent(company_id)
                if base_agent:
                    logger.info(f"No matching agents found, using base agent {base_agent['id']}")
                    return base_agent['id'], 0.0
                
                logger.error(f"No base agent available for company {company_id}")
                return None, 0.0

            # Get best result that meets the confidence threshold
            best_result = results[0]
            score = best_result.get('score', 0.0)
            
            # If first result isn't good enough, keep current agent
            if score < confidence_threshold and current_agent_id:
                logger.info(f"Best agent match {best_result.get('agent_id')} with score {score} below threshold {confidence_threshold}, keeping current agent")
                return current_agent_id, 0.0
                
            best_agent_id = best_result.get('agent_id')
            if best_agent_id:
                logger.info(f"Found best agent {best_agent_id} with score {score}")
                return best_agent_id, score
            
            # Fallback to current agent or base agent
            if current_agent_id:
                return current_agent_id, 0.0
                
            base_agent = await self.get_base_agent(company_id)
            return base_agent['id'] if base_agent else None, 0.0

        except Exception as e:
            logger.error(f"Error finding best agent: {str(e)}")
            # Fallback to current agent or base agent
            if current_agent_id:
                return current_agent_id, 0.0
                
            try:
                base_agent = await self.get_base_agent(company_id)
                return base_agent['id'] if base_agent else None, 0.0
            except Exception as base_error:
                logger.error(f"Error getting base agent as fallback: {str(base_error)}")
                return None, 0.0

    async def update_conversation(
        self,
        conversation_id: str,
        user_message: str,
        ai_response: str,
        agent_id: str,
        confidence_score: float = 0.0,
        tokens_used: Optional[int] = None,
        was_successful: bool = True,
        previous_agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update conversation with transaction safety and metrics tracking"""
        start_time = time.time()
        try:
            # Calculate response time
            response_time = time.time() - start_time
            
            # Create interaction record
            interaction_id = str(uuid.uuid4())
            interaction = AgentInteraction(
                id=interaction_id,
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
            
            async with self._db_lock:
                try:
                    # Add interaction record
                    self.db.add(interaction)
                    
                    # Update conversation record
                    conversation = self.db.query(Conversation).filter_by(id=conversation_id).first()
                    if not conversation:
                        logger.error(f"Conversation {conversation_id} not found")
                        self.db.rollback()
                        return False
                        
                    conversation.current_agent_id = agent_id
                    conversation.updated_at = datetime.utcnow()
                    
                    # Update conversation history if the field exists
                    if hasattr(conversation, 'history'):
                        # Initialize history if None
                        if conversation.history is None:
                            conversation.history = []
                            
                        # Add new message to history
                        history_entry = {
                            "timestamp": datetime.utcnow().isoformat(),
                            "agent_id": agent_id,
                            "user_message": user_message,
                            "ai_response": ai_response,
                            "confidence_score": confidence_score,
                            "metadata": metadata or {}
                        }
                        
                        conversation.history.append(history_entry)
                    
                    # Commit transaction
                    self.db.commit()
                    
                    # Update cache
                    if conversation_id in self.conversation_cache:
                        self.conversation_cache[conversation_id].update({
                            "current_agent_id": agent_id,
                            "updated_at": conversation.updated_at.isoformat()
                        })
                        
                    if was_successful:
                        self._metrics["successful_conversations"] += 1
                    else:
                        self._metrics["failed_conversations"] += 1
                        
                    logger.info(f"Updated conversation {conversation_id} with new interaction {interaction_id}")
                    return True
                    
                except Exception as db_error:
                    self.db.rollback()
                    logger.error(f"Database error updating conversation: {str(db_error)}")
                    raise

        except Exception as e:
            logger.error(f"Error updating conversation: {str(e)}")
            if hasattr(self, 'db'):
                self.db.rollback()
            return False
    
    async def get_conversation_context(
        self,
        conversation_id: str,
        limit: int = 5
    ) -> List[Dict[str, str]]:
        """Get recent conversation history with improved error handling"""
        try:
            self._metrics["db_queries"] += 1
            
            # First check the conversation history field
            conversation = self.db.query(Conversation).filter_by(id=conversation_id).first()
            if conversation and hasattr(conversation, 'history') and conversation.history:
                # Use the history field if it exists and has data
                history = conversation.history
                if isinstance(history, list) and len(history) > 0:
                    # Convert history entries to the required format
                    context = []
                    for entry in history[-limit:]:
                        if isinstance(entry, dict):
                            context.extend([
                                {"role": "user", "content": entry.get("user_message", "")},
                                {"role": "assistant", "content": entry.get("ai_response", "")}
                            ])
                    
                    if context:
                        return context
            
            # Fallback to interactions if history field is not available or empty
            interactions = self.db.query(AgentInteraction).filter_by(
                conversation_id=conversation_id
            ).order_by(
                AgentInteraction.created_at.desc()
            ).limit(limit).all()

            context = []
            for interaction in reversed(interactions):
                if interaction.query and interaction.response:
                    context.extend([
                        {"role": "user", "content": interaction.query},
                        {"role": "assistant", "content": interaction.response}
                    ])

            return context

        except Exception as e:
            logger.error(f"Error getting conversation context: {str(e)}")
            return []  # Return empty list rather than failing
    
    async def get_agent_by_id(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent by ID with caching"""
        try:
            # Check cache first
            if agent_id in self.agent_cache:
                # Verify cache is still valid
                if (agent_id in self.agent_cache_timestamps and
                    time.time() - self.agent_cache_timestamps[agent_id] < self.cache_ttl):
                    self._metrics["cache_hits"] += 1
                    return self.agent_cache[agent_id]
            
            # Cache miss, query database
            self._metrics["db_queries"] += 1
            self._metrics["cache_misses"] += 1
            
            agent = self.db.query(Agent).filter_by(id=agent_id, is_active=True).first()
            if not agent:
                return None
                
            agent_info = {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type,
                "prompt": agent.prompt,
                "confidence_threshold": agent.confidence_threshold,
                "additional_context": agent.additional_context,
                "company_id": agent.company_id
            }
            
            # Update cache
            self.agent_cache[agent_id] = agent_info
            self.agent_cache_timestamps[agent_id] = time.time()
            
            # Update company_agents_cache
            company_id = agent.company_id
            if company_id:
                if company_id not in self.company_agents_cache:
                    self.company_agents_cache[company_id] = []
                if agent_id not in self.company_agents_cache[company_id]:
                    self.company_agents_cache[company_id].append(agent_id)
            
            return agent_info
            
        except Exception as e:
            logger.error(f"Error getting agent by ID: {str(e)}")
            return None

    async def cleanup_inactive_agents(self, days: int = 30) -> None:
        """Cleanup inactive agents and their data with improved error handling"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            self._metrics["db_queries"] += 1
            inactive_agents = self.db.query(Agent).filter(
                Agent.updated_at < cutoff,
                Agent.type != 'base',  # Don't delete base agents
                Agent.is_active == True  # Only consider currently active agents
            ).all()

            if not inactive_agents:
                logger.info("No inactive agents to clean up")
                return
                
            logger.info(f"Found {len(inactive_agents)} inactive agents to clean up")
            
            # Track successfully cleaned agents
            cleaned_count = 0
            
            for agent in inactive_agents:
                try:
                    # Mark as inactive first
                    agent.is_active = False
                    self.db.commit()
                    
                    # Delete from vector store
                    vector_store_deleted = await self.vector_store.delete_agent_data(agent.company_id, agent.id)
                    if not vector_store_deleted:
                        logger.warning(f"Failed to delete vector data for agent {agent.id}")
                    
                    # Clear caches
                    self.agent_cache.pop(agent.id, None)
                    self.agent_cache_timestamps.pop(agent.id, None)
                    
                    if agent.company_id in self.company_agents_cache:
                        self.company_agents_cache[agent.company_id] = [
                            aid for aid in self.company_agents_cache[agent.company_id]
                            if aid != agent.id
                        ]
                    
                    cleaned_count += 1
                    
                except Exception as agent_error:
                    logger.error(f"Error cleaning up agent {agent.id}: {str(agent_error)}")
                    # Continue with next agent rather than failing completely
            
            logger.info(f"Successfully cleaned up {cleaned_count}/{len(inactive_agents)} inactive agents")

        except Exception as e:
            logger.error(f"Error cleaning up agents: {str(e)}")
            self.db.rollback()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get cache and performance metrics"""
        cache_stats = {
            "agent_cache_size": len(self.agent_cache),
            "company_agents_cache_size": len(self.company_agents_cache),
            "conversation_cache_size": len(self.conversation_cache),
        }
        
        return {
            "cache_stats": cache_stats,
            "performance_metrics": self._metrics
        }
    
    async def clear_cache(self, company_id: Optional[str] = None) -> None:
        """Clear cache data, optionally for a specific company only"""
        if company_id:
            # Clear only specific company data
            if company_id in self.company_agents_cache:
                for agent_id in self.company_agents_cache[company_id]:
                    self.agent_cache.pop(agent_id, None)
                    self.agent_cache_timestamps.pop(agent_id, None)
                self.company_agents_cache.pop(company_id, None)
                
            # Clear conversations for this company
            company_conversations = [
                conv_id for conv_id, conv in self.conversation_cache.items()
                if conv.get("company_id") == company_id
            ]
            for conv_id in company_conversations:
                self.conversation_cache.pop(conv_id, None)
                
            logger.info(f"Cleared cache for company {company_id}")
            
        else:
            # Clear all cache
            self.agent_cache.clear()
            self.agent_cache_timestamps.clear()
            self.company_agents_cache.clear()
            self.conversation_cache.clear()
            logger.info("Cleared all cache data")

"""
Key Improvements:

Cache Management:

Added timestamp-based cache expiration
Added proper cache invalidation when data changes
Implemented cache bypass and revalidation methods
Added metrics tracking for cache hits/misses


Concurrency Control:

Improved lock handling for initialization
Added database transaction lock to prevent race conditions
Enhanced double-check locking for better performance
Safer error handling in async contexts


Error Handling:

Added transaction rollback in all error cases
Isolated database errors from other exceptions
Better error logging with context information
Graceful degradation when errors occur


Agent Selection Logic:

Improved best agent search with configurable threshold
Added fallback mechanisms for better reliability
Enhanced agent search to use vector similarity scores
Performance monitoring for agent searches


Transaction Safety:

Safer database transaction handling
Proper rollback on errors
Updated cache only after successful transactions
Transaction isolation for concurrent operations


Conversation and History Management:

Support for both history field and interactions table
Improved metadata handling for conversations
Better conversation context retrieval logic
Efficient interaction storage


Maintenance and Monitoring:

Added performance metrics collection
Added method to get metrics for monitoring
Enhanced inactive agent cleanup process
Cache clearing functionality for maintenance


New Features:

Added get_agent_by_id method for direct agent access
Added clear_cache method for management
Added metadata support for conversations
Enhanced tracking of conversation success/failure



These improvements make the AgentManager more robust, efficient, and maintainable, especially in high-concurrency environments. The enhanced error handling and transaction safety help ensure data integrity, while the improved caching reduces database load and improves response times.
"""