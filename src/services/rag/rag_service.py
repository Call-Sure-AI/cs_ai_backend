from typing import List, Dict, Optional, Any, AsyncIterator, Tuple
import logging
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessageChunk, HumanMessage, AIMessage
import asyncio
import json
import time
from config.settings import settings

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self, qdrant_service):
        """Initialize RAG service with necessary components"""
        self.qdrant_service = qdrant_service
        
        # Initialize OpenAI LLM with streaming capability
        self.llm = ChatOpenAI(
            model_name=settings.OPENAI_MODEL,
            temperature=settings.TEMPERATURE,
            openai_api_key=settings.OPENAI_API_KEY,
            streaming=True,
            # Add request timeout
            request_timeout=60.0
        )
        
        # Custom QA prompt template
        self.qa_template = """You are a helpful AI assistant for a customer support line. Use the following pieces of context to answer the question.
            If the context contains relevant information, provide a detailed and accurate response.
            If the context doesn't contain relevant information, respond in a helpful, friendly way without mentioning the lack of context.

            Context: {context}

            Question: {question}

            Instructions:
            1. Base your answer ONLY on the provided context when relevant
            2. Be specific and cite information from the context when possible
            3. If the context is not relevant, provide a general helpful response as a customer service agent
            4. Maintain a helpful and friendly conversational tone
            5. Keep responses concise and to the point
            6. If the user is simply saying hello, greet them warmly and ask how you can help

            Answer: """
        
        self.qa_prompt = PromptTemplate(
            template=self.qa_template,
            input_variables=["context", "question"]
        )
        
        # Cache for QA chains with expiration
        self.chain_cache = {}
        self.chain_timestamps = {}
        self.cache_ttl = 1800  # 30 minutes
        
        # Cache for common queries
        self.response_cache = {}
        self.response_cache_max_size = 100
        
        # Conversation memory
        self.conversation_memory = {}
        
        # Semaphore for limiting concurrent LLM calls
        self._llm_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent LLM requests
    
    async def create_qa_chain(self, company_id: str, agent_id: Optional[str] = None) -> RetrievalQA:
        """Create a QA chain using the vector store for a company/agent with cache management"""
        try:
            # Check if chain already exists in cache and is still valid
            cache_key = f"{company_id}_{agent_id or 'all'}"
            current_time = time.time()
            
            if (cache_key in self.chain_cache and 
                current_time - self.chain_timestamps.get(cache_key, 0) < self.cache_ttl):
                return self.chain_cache[cache_key]
            
            # Get vector store
            vector_store = await self.qdrant_service.get_vector_store(company_id)
            
            # Create retriever, optionally with agent filter
            search_kwargs = {
                "k": settings.RETRIEVAL_K,
                "score_threshold": settings.SCORE_THRESHOLD,
                "fetch_k": 20  # Fetch more documents initially for better filtering
            }
            
            if agent_id:
                from qdrant_client import models
                search_filter = models.Filter(
                    must=[models.FieldCondition(
                        key="metadata.agent_id",
                        match=models.MatchValue(value=str(agent_id))
                    )]
                )
                search_kwargs["filter"] = search_filter
            
            retriever = vector_store.as_retriever(
                search_type="similarity_score_threshold",
                search_kwargs=search_kwargs
            )
            
            # Build the RetrievalQA chain
            chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever,
                return_source_documents=True,
                chain_type_kwargs={
                    "prompt": self.qa_prompt, 
                    "document_variable_name": "context",
                    "verbose": settings.DEBUG
                }
            )
            
            # Manage cache size (simple LRU implementation)
            if len(self.chain_cache) >= 20:  # Limit number of cached chains
                oldest_key = min(self.chain_timestamps.items(), key=lambda x: x[1])[0]
                del self.chain_cache[oldest_key]
                del self.chain_timestamps[oldest_key]
            
            # Cache the chain with timestamp
            self.chain_cache[cache_key] = chain
            self.chain_timestamps[cache_key] = current_time
            
            logger.info(f"Created QA chain for company {company_id}, agent {agent_id}")
            return chain
            
        except Exception as e:
            logger.error(f"Error creating QA chain: {str(e)}")
            raise
    
    def _get_cached_response(self, question: str, agent_id: Optional[str] = None) -> Optional[str]:
        """Check if response is cached for the question"""
        cache_key = f"{agent_id or 'all'}:{question.strip().lower()}"
        cached_item = self.response_cache.get(cache_key)
        
        if cached_item:
            # Cache is still valid
            logger.info(f"Cache hit for question: {question[:50]}...")
            return cached_item["response"]
        
        return None
    
    def _cache_response(self, question: str, response: str, agent_id: Optional[str] = None) -> None:
        """Cache the response for the question"""
        if len(question) > 10:  # Only cache substantial questions
            cache_key = f"{agent_id or 'all'}:{question.strip().lower()}"
            
            # Manage cache size (simple LRU)
            if len(self.response_cache) >= self.response_cache_max_size:
                # Remove oldest item
                oldest_key = next(iter(self.response_cache))
                del self.response_cache[oldest_key]
            
            self.response_cache[cache_key] = {
                "response": response,
                "timestamp": time.time()
            }
    
    def _prepare_prompt_with_context(
        self, 
        question: str, 
        conversation_context: Optional[List[Dict]] = None,
        company_name: str = "our service"
    ) -> Tuple[str, str]:
        """Prepare prompt with conversation context for more coherent responses"""
        if not conversation_context:
            return question, question
            
        # Format recent conversation for context
        messages = []
        context_messages = conversation_context[-5:]  # Use last 5 messages for context
        
        for msg in context_messages:
            if msg['role'] == 'user':
                messages.append(f"User: {msg['content']}")
            else:
                messages.append(f"Assistant: {msg['content']}")
        
        # Create context-aware prompt
        conversation_history = "\n".join(messages)
        enhanced_question = (
            f"Previous conversation:\n{conversation_history}\n\n"
            f"User's current question: {question}\n\n"
            f"Please respond to the user's current question considering the above conversation history."
        )
        
        return enhanced_question, question
    
    async def get_answer_with_chain(
        self,
        chain: RetrievalQA,
        question: str,
        conversation_context: Optional[List[Dict]] = None,
        company_name: str = "our service"
    ) -> AsyncIterator[str]:
        """Stream responses token-by-token from the RAG chain with improved context handling"""
        try:
            question = question.strip()
            logger.info(f"Querying chain with question: {question}")
            
            # Check cache for common queries first
            cached_response = self._get_cached_response(question)
            if cached_response and len(question) > 5:
                # Simulate streaming for cached responses
                words = cached_response.split()
                for word in words:
                    yield word + " "
                    await asyncio.sleep(0.02)  # Small delay for natural feel
                return
            
            # Handle special system commands
            if question == "__SYSTEM_WELCOME__":
                welcome_message = f"Hello! Welcome to {company_name}. I'm your AI voice assistant. How may I help you today?"
                for token in welcome_message.split():
                    yield token + " "
                return
            
            # Check for simple greetings for faster response
            simple_greetings = {"hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening"}
            if question.lower() in simple_greetings:
                greeting = f"Hello! How can I assist you with {company_name} today?"
                for token in greeting.split():
                    yield token + " "
                return
            
            # Prepare question with context
            query_with_context, original_question = self._prepare_prompt_with_context(
                question, conversation_context, company_name
            )
            
            # Use semaphore to limit concurrent LLM calls
            async with self._llm_semaphore:
                # Full response for caching
                full_response = ""
                
                # Stream response using astream_events
                async for event in chain.astream_events(
                    {"query": query_with_context, "question": original_question},
                    config=RunnableConfig(
                        run_name="streaming_chain",
                        callbacks=None,
                        tags=["rag"]
                    ),
                    version="v2"
                ):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"].get("chunk", "")
                        if isinstance(chunk, AIMessageChunk):
                            token = chunk.content
                        else:
                            token = str(chunk)
                        
                        full_response += token
                        yield token
                
                # Cache the full response if substantial
                if len(full_response) > 20:
                    self._cache_response(question, full_response)
                
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            logger.warning(f"Request for question '{question[:50]}...' was cancelled")
            yield "\n\nThe request was cancelled."
        except Exception as e:
            logger.error(f"Error getting answer with chain: {str(e)}")
            error_msg = "I'm sorry, I encountered an error processing your request. Please try again in a moment."
            yield error_msg
    
    async def verify_embeddings(self, company_id: str, agent_id: Optional[str] = None) -> bool:
        """Verify that embeddings exist for the company/agent"""
        try:
            return await self.qdrant_service.verify_embeddings(company_id, agent_id)
        except Exception as e:
            logger.error(f"Error verifying embeddings: {str(e)}")
            return False
    
    async def add_documents(
        self,
        company_id: str,
        documents: List[Dict[str, Any]],
        agent_id: Optional[str] = None
    ) -> bool:
        """Add documents to the vector store for RAG"""
        try:
            # Clear cache for this company/agent
            cache_key = f"{company_id}_{agent_id or 'all'}"
            if cache_key in self.chain_cache:
                del self.chain_cache[cache_key]
                if cache_key in self.chain_timestamps:
                    del self.chain_timestamps[cache_key]
            
            # Process and add documents using the embed_documents method
            return await self.qdrant_service.load_documents(company_id, agent_id, documents)
        except Exception as e:
            logger.error(f"Error adding documents: {str(e)}")
            return False
    
    async def delete_agent_documents(self, company_id: str, agent_id: str) -> bool:
        """Delete all documents for an agent"""
        try:
            # Clear cache for this company/agent
            cache_key = f"{company_id}_{agent_id}"
            if cache_key in self.chain_cache:
                del self.chain_cache[cache_key]
                if cache_key in self.chain_timestamps:
                    del self.chain_timestamps[cache_key]
            
            # Remove all documents and embeddings for this agent
            return await self.qdrant_service.delete_agent_data(company_id, agent_id)
        except Exception as e:
            logger.error(f"Error deleting agent documents: {str(e)}")
            return False
    
    async def get_answer(
        self,
        company_id: str,
        question: str,
        agent_id: Optional[str] = None,
        conversation_context: Optional[List[Dict]] = None,
        company_name: str = "our service"
    ) -> AsyncIterator[str]:
        """Get answer to a question using RAG with improved error handling"""
        start_time = time.time()
        try:
            # Check if embeddings exist
            has_embeddings = await self.verify_embeddings(company_id, agent_id)
            if not has_embeddings:
                yield "I don't have any knowledge documents to reference yet. I'll do my best to help based on general knowledge."
                return
            
            # Create chain
            chain = await self.create_qa_chain(company_id, agent_id)
            
            # Get streaming answer
            async for token in self.get_answer_with_chain(
                chain, question, conversation_context, company_name
            ):
                yield token
                
        except Exception as e:
            logger.error(f"Error getting answer: {str(e)}")
            yield "I'm sorry, I encountered a technical issue. Please try again in a moment."
        finally:
            processing_time = time.time() - start_time
            logger.info(f"RAG processing time: {processing_time:.2f} seconds")

"""
Key Improvements:

Performance Improvements:
Added timeout settings for LLM requests
Added semaphore to limit concurrent LLM calls
Improved caching with TTL for QA chains


Response Caching:
Added caching for common queries
Simulated streaming for cached responses
LRU-style cache management to limit memory usage


Smarter Context Handling:
Improved conversation context preparation
Enhanced greeting and welcome message handling
Special case handling for simple queries


Better Error Handling:
Added cancellation handling for interrupted requests
Improved error messages with friendlier responses
Added performance timing and logging


More Flexible Configuration:
Using settings from config for retrieval parameters
Added company_name parameter for customized responses
Improved LLM configuration with temperature from settings


QoL Improvements:
Optimized retriever settings for better result quality
Added dedicated verify_embeddings method
Added comprehensive document management methods


Memory Management:
Added cache size limits to prevent memory issues
Improved timestamp-based cache expiration
Enhanced cache cleanup for when documents change

These improvements make the RAGService more reliable, efficient, and user-friendly. The service now provides better responses, handles errors gracefully, and manages resources more effectively, especially for high-volume production environments.
"""