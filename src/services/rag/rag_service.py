from typing import List, Dict, Optional, Any, AsyncIterator
import logging
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessageChunk
import asyncio
import json
from config.settings import settings
from .communication_intent_detector import CommunicationIntentDetector

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self, qdrant_service):
        """Initialize RAG service with necessary components"""
        self.qdrant_service = qdrant_service
        self.intent_detector = CommunicationIntentDetector()
        # Initialize OpenAI LLM
        self.llm = ChatOpenAI(
            model_name=settings.OPENAI_MODEL,
            temperature=0.1,
            openai_api_key=settings.OPENAI_API_KEY
        )
        
        # Custom QA prompt template
        self.qa_template = """You are a helpful AI assistant. Use the following pieces of context to answer the question. 
        If the context contains relevant information, provide a detailed and accurate response.
        If the context doesn't contain relevant information, simply state that you don't have information about that specific topic.
        
        Context: {context}
        
        Question: {question}
        
        Instructions:
        1. Base your answer ONLY on the provided context
        2. Be specific and cite information from the context
        3. If the context is relevant but incomplete, mention what is known while acknowledging limitations
        4. Maintain a helpful and informative tone
        
        Answer: """
        
        self.qa_prompt = PromptTemplate(
            template=self.qa_template,
            input_variables=["context", "question"]
        )
        
        # Caching mechanism for chains
        self.chain_cache = {}
    
    # Add this new method to your RAGService class
    async def process_communication_intent(
        self, 
        question: str, 
        conversation_context: List[Dict],
        webrtc_manager=None,
        client_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Process any communication intents (sending email, scheduling meeting)
        Returns a dictionary if an intent was detected and processed, None otherwise
        """
        try:
            # Detect the intent
            intent_result = await self.intent_detector.detect_intent(question)
            
            if not intent_result.get("has_intent", False) or not webrtc_manager or not client_id:
                return None
            
            intent_type = intent_result.get("intent_type")
            
            # Process email intent
            if intent_type == "email":
                # Extract detailed email information
                email_details = await self.intent_detector.extract_email_details(
                    conversation_history=conversation_context,
                    current_request=question
                )
                
                # Handle the email request
                result = await webrtc_manager.handle_communication_request(
                    client_id=client_id,
                    action="send_email",
                    params=email_details
                )
                
                return {
                    "action": "email",
                    "result": result,
                    "details": email_details
                }
            
            # Process meeting intent
            elif intent_type == "meeting":
                # Extract detailed meeting information
                meeting_details = await self.intent_detector.extract_meeting_details(
                    conversation_history=conversation_context,
                    current_request=question
                )
                
                # Handle the meeting request
                result = await webrtc_manager.handle_communication_request(
                    client_id=client_id,
                    action="schedule_meeting",
                    params=meeting_details
                )
                
                return {
                    "action": "meeting",
                    "result": result,
                    "details": meeting_details
                }
            
            return None
                
        except Exception as e:
            logger.error(f"Error processing communication intent: {str(e)}", exc_info=True)
            return None
    
    
    async def create_qa_chain(self, company_id: str, agent_id: Optional[str] = None) -> RetrievalQA:
        """Create a QA chain using the vector store for a company/agent"""
        try:
            # Check if chain already exists in cache
            cache_key = f"{company_id}_{agent_id or 'all'}"
            if cache_key in self.chain_cache:
                return self.chain_cache[cache_key]
            
            # Get vector store
            vector_store = await self.qdrant_service.get_vector_store(company_id)
            
            # Create retriever, optionally with agent filter
            search_kwargs = {"k": 5, "score_threshold": 0.2}
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
                search_type="similarity",
                search_kwargs=search_kwargs
            )
            
            # Build the RetrievalQA chain
            chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever,
                return_source_documents=True,
                chain_type_kwargs={"prompt": self.qa_prompt, "document_variable_name": "context"}
            )
            
            # Cache the chain
            self.chain_cache[cache_key] = chain
            
            logger.info(f"Created QA chain for company {company_id}, agent {agent_id}")
            return chain
            
        except Exception as e:
            logger.error(f"Error creating QA chain: {str(e)}")
            raise
    
    # async def get_answer_with_chain(
    #     self,
    #     chain: RetrievalQA,
    #     question: str,
    #     conversation_context: Optional[List[Dict]] = None
    # ) -> AsyncIterator[str]:
    #     """Stream responses token-by-token from the RAG chain"""
    #     try:
    #         logger.info(f"Querying chain with question: {question}")
            
    #         # Add conversation context if available
    #         query_with_context = question
    #         if conversation_context:
    #             recent_messages = "\n".join([
    #                 f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
    #                 for msg in conversation_context[-3:]  # Use last 3 messages
    #             ])
                
    #             query_with_context = f"{recent_messages}\n\nCurrent question: {question}"
    #             logger.info(f"Added conversation context: {recent_messages[:100]}...")
            
    #         # Stream response using astream_events
    #         async for event in chain.astream_events(
    #             {"query": query_with_context, "question": question},
    #             config=RunnableConfig(run_name="streaming_chain"),
    #             version="v2"
    #         ):
    #             if event["event"] == "on_chat_model_stream":
    #                 chunk = event["data"].get("chunk", "")
    #                 if isinstance(chunk, AIMessageChunk):
    #                     token = chunk.content
    #                 else:
    #                     token = str(chunk)
                    
    #                 yield token
                
    #     except Exception as e:
    #         logger.error(f"Error getting answer with chain: {str(e)}")
    #         yield "I encountered an error processing your question."
    
    
    async def get_answer_with_chain(
        self,
        chain,
        question: str,
        conversation_context: Optional[List[Dict]] = None,
        webrtc_manager=None,
        client_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream responses token-by-token from the RAG chain with communication intent handling"""
        try:
            logger.info(f"Querying chain with question: {question}")
            
            # First, check for communication intents
            if webrtc_manager and client_id:
                communication_result = await self.process_communication_intent(
                    question=question,
                    conversation_context=conversation_context or [],
                    webrtc_manager=webrtc_manager,
                    client_id=client_id
                )
                logger.info(f"Communication intent result: {communication_result}")
                if communication_result:
                    # If communication intent was processed, generate a response about it
                    action = communication_result["action"]
                    result = communication_result["result"]
                    details = communication_result["details"]
                    
                    if action == "email":
                        if result.get("status") == "success":
                            response = f"I've sent an email to {', '.join(details.get('to', []))} "
                            response += f"with the subject '{details.get('subject', 'No subject')}'. "
                            if "email_id" in result:
                                response += f"The email was sent successfully (ID: {result['email_id']})."
                            else:
                                response += "The email was sent successfully."
                        else:
                            response = f"I wasn't able to send the email: {result.get('message', 'Unknown error')}."
                        
                        # Yield the response
                        for char in response:
                            yield char
                        return
                        
                    elif action == "meeting":
                        if result.get("status") == "success":
                            meeting = result.get("meeting", {})
                            response = f"I've scheduled a meeting titled '{meeting.get('title', 'No title')}' "
                            response += f"for {meeting.get('start_time', 'the specified time')}. "
                            
                            if meeting.get("meet_link"):
                                response += f"Here's the Google Meet link: {meeting['meet_link']}. "
                            
                            response += f"I've sent invitations to {', '.join(details.get('attendees', []))}."
                        else:
                            response = f"I wasn't able to schedule the meeting: {result.get('message', 'Unknown error')}."
                        
                        # Yield the response
                        for char in response:
                            yield char
                        return
            
            # Continue with your existing code for normal RAG processing...
            # Add conversation context if available
            query_with_context = question
            if conversation_context:
                recent_messages = "\n".join([
                    f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
                    for msg in conversation_context[-3:]  # Use last 3 messages
                ])
                
                query_with_context = f"{recent_messages}\n\nCurrent question: {question}"
                logger.info(f"Added conversation context: {recent_messages[:100]}...")
            
            async for event in chain.astream_events(
                {"query": query_with_context, "question": question},
                config=RunnableConfig(run_name="streaming_chain"),
                version="v2"
            ):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"].get("chunk", "")
                    if isinstance(chunk, AIMessageChunk):
                        token = chunk.content
                    else:
                        token = str(chunk)
                    
                    yield token
                
            
        except Exception as e:
            logger.error(f"Error getting answer with chain: {str(e)}")
            yield "I encountered an error processing your question."
    
    
    
    async def get_answer(
        self,
        company_id: str,
        question: str,
        agent_id: Optional[str] = None,
        conversation_context: Optional[List[Dict]] = None
    ) -> AsyncIterator[str]:
        """Get answer to a question using RAG"""
        try:
            # Check if embeddings exist
            has_embeddings = await self.qdrant_service.verify_embeddings(company_id, agent_id)
            if not has_embeddings:
                yield "I don't have any knowledge documents to reference. Please add some documents first."
                return
            
            # Create chain
            chain = await self.create_qa_chain(company_id, agent_id)
            
            # Get streaming answer
            async for token in self.get_answer_with_chain(chain, question, conversation_context):
                yield token
                
        except Exception as e:
            logger.error(f"Error getting answer: {str(e)}")
            yield "I encountered an error processing your question."