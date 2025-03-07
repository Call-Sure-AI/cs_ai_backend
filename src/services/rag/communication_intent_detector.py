# services/rag/communication_intent_detector.py
from typing import Dict, Any, Optional, List, Tuple
import re
import logging
from datetime import datetime, timedelta
import pytz
import json
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import asyncio
from config.settings import settings

logger = logging.getLogger(__name__)

class CommunicationIntentDetector:
    """
    Detects and processes communication intents from user queries such as:
    - Send an email
    - Schedule a meeting
    """
    
    def __init__(self):
        """Initialize the intent detector"""
        try:
            self.llm = ChatOpenAI(
                model_name=settings.OPENAI_MODEL,
                temperature=0.1,
                openai_api_key=settings.OPENAI_API_KEY
            )
            logger.info("Communication intent detector initialized with OpenAI model")
        except Exception as e:
            logger.error(f"Error initializing intent detector: {str(e)}")
            # Create a fallback to ensure the class doesn't fail to initialize
            self.llm = None
        
        # Intent detection prompt - Fixed the template string format issue
        self.intent_prompt = PromptTemplate(
            template="""You are analyzing user messages to detect if they want to schedule a meeting or send an email. 
            
            Examples of meeting scheduling intents:
            - "Schedule a meeting with the team next Tuesday at 2pm"
            - "I need to set up a call with John to discuss the project"
            - "Can you arrange a Google Meet tomorrow morning?"
            
            Examples of email sending intents:
            - "Send an email to john@example.com about the project timeline"
            - "I need to email the team about the meeting tomorrow"
            - "Write to Jane with information about our services"
            
            User message: {user_message}
            
            Return a JSON with the following structure:
            {{
                "has_intent": true/false,
                "intent_type": "meeting" or "email" or null,
                "confidence": 0-1 (how confident you are about the intent),
                "entities": {{
                    // For emails
                    "recipients": ["email1", "email2"] or [description of recipients],
                    "subject": "detected subject",
                    "body": "detected content",
                    
                    // For meetings
                    "attendees": ["email1", "email2"] or [description of attendees],
                    "title": "detected meeting title",
                    "description": "detected meeting description",
                    "start_time": "detected time" (as descriptive as possible),
                    "duration": "detected duration"
                }}
            }}
            
            If there's no clear intent to schedule a meeting or send an email, return "has_intent": false and leave the other fields empty or null.
            """,
            input_variables=["user_message"]
        )
        
        # Email extraction prompt
        self.email_prompt = PromptTemplate(
            template="""Based on the conversation history and the current request to send an email, craft a complete email with all necessary details.

            Conversation History:
            {conversation_history}
            
            Current Request:
            {current_request}
            
            Extract and organize the following email information in JSON format:
            {{
                "to": ["email1@example.com", "email2@example.com"],
                "cc": ["cc1@example.com"] or [],
                "subject": "Detected email subject",
                "body": "Full email body text that should be sent",
                "html_body": "HTML formatted version of the email (if applicable, otherwise null)",
                "reply_to": "reply@example.com" or null
            }}
            
            If email addresses are not explicitly mentioned but recipients are described (e.g. "the team", "John"), include them as described in the "to" field.
            If any field is not specified or cannot be determined, use reasonable defaults or return null for optional fields.
            """,
            input_variables=["conversation_history", "current_request"]
        )
        
        # Meeting extraction prompt
        self.meeting_prompt = PromptTemplate(
            template="""Based on the conversation history and the current request to schedule a meeting, craft complete meeting details.

            Conversation History:
            {conversation_history}
            
            Current Request:
            {current_request}
            
            Extract and organize the following meeting information in JSON format:
            {{
                "title": "Detected meeting title",
                "description": "Detailed meeting description and agenda",
                "start_time": "Specific date and time in format YYYY-MM-DD HH:MM",
                "duration_minutes": minutes (e.g. 30, 60),
                "timezone": "UTC" or specified timezone,
                "attendees": ["email1@example.com", "email2@example.com"] or ["described person1", "described person2"],
                "additional_message": "Any additional message to include with the invitation"
            }}
            
            If specific date/time is not given, choose a reasonable near-future time during business hours.
            If duration is not specified, default to 30 minutes.
            If timezone is not specified, default to UTC.
            If any field cannot be determined, use reasonable defaults.
            """,
            input_variables=["conversation_history", "current_request"]
        )
    
    async def detect_intent(self, user_message: str) -> Dict[str, Any]:
        """Detect if the user message contains a communication intent"""
        try:
            if not self.llm:
                logger.warning("LLM not initialized, skipping intent detection")
                return {"has_intent": False}
                
            logger.info(f"Detecting intent for message: {user_message[:100]}...")
            
            # Generate the prompt
            prompt = self.intent_prompt.format(user_message=user_message)
            
            # Get response from LLM
            response = await asyncio.to_thread(
                self.llm.invoke,
                prompt
            )
            
            # Parse JSON response
            try:
                # First, extract JSON from the response if needed
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                result = json.loads(content)
                logger.info(f"Intent detection result: {result.get('has_intent')}, type: {result.get('intent_type')}")
                return result
            except json.JSONDecodeError:
                logger.error(f"Failed to parse intent response: {response.content}")
                return {"has_intent": False}
                
        except Exception as e:
            logger.error(f"Error detecting communication intent: {str(e)}", exc_info=True)
            return {"has_intent": False}
    
    async def extract_email_details(
        self,
        conversation_history: List[Dict[str, str]],
        current_request: str
    ) -> Dict[str, Any]:
        """Extract detailed email information from the request"""
        try:
            if not self.llm:
                logger.warning("LLM not initialized, skipping email extraction")
                return {
                    "to": [],
                    "subject": "Error: LLM not initialized",
                    "body": "Sorry, the email service is not available at the moment."
                }
                
            logger.info("Extracting email details...")
            
            # Format conversation history
            history_text = "\n".join([
                f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
                for msg in conversation_history[-5:]  # Use last 5 messages
            ])
            
            # Generate the prompt
            prompt = self.email_prompt.format(
                conversation_history=history_text,
                current_request=current_request
            )
            
            # Get response from LLM
            response = await asyncio.to_thread(
                self.llm.invoke,
                prompt
            )
            
            # Parse JSON response
            try:
                # Extract JSON from the response
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                result = json.loads(content)
                logger.info(f"Extracted email details: to={result.get('to')}, subject={result.get('subject')}")
                return result
            except json.JSONDecodeError:
                logger.error(f"Failed to parse email details: {response.content}")
                return {
                    "to": [],
                    "subject": "Error extracting email details",
                    "body": "Sorry, I couldn't extract the email details properly."
                }
                
        except Exception as e:
            logger.error(f"Error extracting email details: {str(e)}", exc_info=True)
            return {
                "to": [],
                "subject": "Error processing request",
                "body": f"Error: {str(e)}"
            }
    
    async def extract_meeting_details(
        self,
        conversation_history: List[Dict[str, str]],
        current_request: str
    ) -> Dict[str, Any]:
        """Extract detailed meeting information from the request"""
        try:
            if not self.llm:
                logger.warning("LLM not initialized, skipping meeting extraction")
                return {
                    "title": "Error: LLM not initialized",
                    "description": "Sorry, the meeting scheduling service is not available at the moment.",
                    "start_time": datetime.now() + timedelta(hours=1),
                    "duration_minutes": 30,
                    "timezone": "UTC",
                    "attendees": []
                }
                
            logger.info("Extracting meeting details...")
            
            # Format conversation history
            history_text = "\n".join([
                f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
                for msg in conversation_history[-5:]  # Use last 5 messages
            ])
            
            # Generate the prompt
            prompt = self.meeting_prompt.format(
                conversation_history=history_text,
                current_request=current_request
            )
            
            # Get response from LLM
            response = await asyncio.to_thread(
                self.llm.invoke,
                prompt
            )
            
            # Parse JSON response
            try:
                # Extract JSON from the response
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                result = json.loads(content)
                
                # Convert start_time to datetime if it's a string
                if isinstance(result.get("start_time"), str):
                    try:
                        # Try to parse the datetime string
                        result["start_time"] = datetime.fromisoformat(
                            result["start_time"].replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        # If parsing fails, use a default time (1 hour from now)
                        result["start_time"] = datetime.now() + timedelta(hours=1)
                        logger.warning(f"Failed to parse meeting start_time, using default: {result['start_time']}")
                
                logger.info(f"Extracted meeting details: title={result.get('title')}, start_time={result.get('start_time')}")
                return result
            except json.JSONDecodeError:
                logger.error(f"Failed to parse meeting details: {response.content}")
                return {
                    "title": "Error extracting meeting details",
                    "description": "Sorry, I couldn't extract the meeting details properly.",
                    "start_time": datetime.now() + timedelta(hours=1),
                    "duration_minutes": 30,
                    "timezone": "UTC",
                    "attendees": []
                }
                
        except Exception as e:
            logger.error(f"Error extracting meeting details: {str(e)}", exc_info=True)
            return {
                "title": "Error processing request",
                "description": f"Error: {str(e)}",
                "start_time": datetime.now() + timedelta(hours=1),
                "duration_minutes": 30,
                "timezone": "UTC",
                "attendees": []
            }