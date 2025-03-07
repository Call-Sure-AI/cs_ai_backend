# services/communication/agent_communication.py
from typing import List, Dict, Any, Optional
import logging
import asyncio
import os
from datetime import datetime, timedelta
from services.email.gmail_service import GmailService, EmailConfig
from services.calendar.google_meet_service import GoogleMeetService
from services.calendar.async_google_calendar import AsyncGoogleCalendar
from services.calendar.types import CalendarConfig, EventOptions

logger = logging.getLogger(__name__)

class AgentCommunicationService:
    def __init__(
        self,
        service_account_json: str,
        sender_email: str,
        calendar_id: str
    ):
        """Initialize the agent communication service with email and calendar capabilities"""
        self.service_account_json = service_account_json
        self.sender_email = sender_email
        self.calendar_id = calendar_id
        
        # Log initialization
        logger.info(f"Initializing AgentCommunicationService with sender: {sender_email}, calendar: {calendar_id}")
        logger.info(f"Using service account: {service_account_json}")
        
        # Check if service account file exists
        if not os.path.isfile(service_account_json):
            logger.error(f"Service account file not found: {service_account_json}")
            raise ValueError(f"Service account file not found: {service_account_json}")
        
        # Initialize email service
        email_config = EmailConfig(
            service_account_json=service_account_json,
            sender_email=sender_email
        )
        self.email_service = GmailService(email_config)
        
        # Initialize calendar service
        calendar_config = CalendarConfig(
            service_account_json=service_account_json,
            calendar_id=calendar_id,
            token_store_path=None  # Not needed for service account
        )
        self.calendar_service = AsyncGoogleCalendar(calendar_config)
        
        # Initialize Google Meet service
        self.meet_service = GoogleMeetService(self.calendar_service)
        
        logger.info("AgentCommunicationService initialization complete")
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html_body: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email on behalf of the agent"""
        try:
            logger.info(f"Agent sending email to {to} with subject: {subject}")
            
            result = await self.email_service.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                html_body=html_body,
                reply_to=reply_to
            )
            
            logger.info(f"Email sent successfully, ID: {result.get('id', 'unknown')}")
            
            return {
                'status': 'success',
                'message': 'Email sent successfully',
                'email_id': result.get('id', None)
            }
            
        except Exception as e:
            logger.error(f"Error sending email via agent: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': f'Failed to send email: {str(e)}'
            }
    
    async def schedule_meeting(
        self,
        title: str,
        description: str,
        start_time: datetime,
        duration_minutes: int,
        timezone: str,
        attendees: List[str],
        send_invites: bool = True
    ) -> Dict[str, Any]:
        """Schedule a meeting with Google Meet on behalf of the agent"""
        try:
            logger.info(f"Agent scheduling meeting: '{title}' at {start_time}")
            
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # Check if the time slot is available
            is_available = await self.calendar_service.check_availability(start_time, end_time)
            if not is_available:
                logger.warning(f"Requested time slot is not available: {start_time} to {end_time}")
                return {
                    'status': 'error',
                    'message': 'The requested time slot is not available'
                }
            
            # Create meeting with Google Meet
            result = await self.meet_service.create_meet_event(
                title=title,
                description=description,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                attendees=attendees,
                send_invites=send_invites
            )
            
            # Extract the meeting details
            meet_info = result.get('meet_info', {})
            event = result.get('event', {})
            
            logger.info(f"Meeting scheduled successfully, ID: {event.get('id', 'unknown')}")
            if meet_info and meet_info.get('meet_link'):
                logger.info(f"Google Meet link: {meet_info.get('meet_link')}")
            
            return {
                'status': 'success',
                'message': 'Meeting scheduled successfully',
                'meeting': {
                    'event_id': event.get('id'),
                    'title': event.get('summary'),
                    'description': event.get('description'),
                    'start_time': event.get('start', {}).get('dateTime'),
                    'end_time': event.get('end', {}).get('dateTime'),
                    'meet_link': meet_info.get('meet_link') if meet_info else None,
                    'calendar_link': event.get('htmlLink')
                }
            }
            
        except Exception as e:
            logger.error(f"Error scheduling meeting via agent: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': f'Failed to schedule meeting: {str(e)}'
            }
    
    async def send_meeting_invitation(
        self,
        meeting_details: Dict[str, Any],
        to: List[str],
        additional_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email with meeting details and Google Meet link"""
        try:
            # Extract meeting details
            title = meeting_details.get('title', 'Meeting')
            start_time = meeting_details.get('start_time')
            end_time = meeting_details.get('end_time')
            meet_link = meeting_details.get('meet_link')
            calendar_link = meeting_details.get('calendar_link')
            
            logger.info(f"Sending meeting invitation email for '{title}' to {to}")
            
            # Format the email
            subject = f"Invitation: {title}"
            
            # Create HTML body
            html_body = f"""
            <html>
            <body>
                <h2>Meeting Invitation: {title}</h2>
                <p>You are invited to a meeting scheduled by our AI assistant.</p>
                
                <h3>Meeting Details:</h3>
                <ul>
                    <li><strong>Date and Time:</strong> {start_time} to {end_time}</li>
                    <li><strong>Google Meet Link:</strong> <a href="{meet_link}">{meet_link}</a></li>
                </ul>
                
                <p>You can add this meeting to your calendar using this link: <a href="{calendar_link}">Add to Calendar</a></p>
                
                {f"<p>Additional Message: {additional_message}</p>" if additional_message else ""}
                
                <p>Looking forward to meeting with you!</p>
            </body>
            </html>
            """
            
            # Create plain text body
            plain_body = f"""
            Meeting Invitation: {title}
            
            You are invited to a meeting scheduled by our AI assistant.
            
            Meeting Details:
            - Date and Time: {start_time} to {end_time}
            - Google Meet Link: {meet_link}
            
            You can add this meeting to your calendar using this link: {calendar_link}
            
            {f"Additional Message: {additional_message}" if additional_message else ""}
            
            Looking forward to meeting with you!
            """
            
            # Send the email
            result = await self.email_service.send_email(
                to=to,
                subject=subject,
                body=plain_body,
                html_body=html_body
            )
            
            logger.info(f"Meeting invitation email sent successfully, ID: {result.get('id', 'unknown')}")
            
            return {
                'status': 'success',
                'message': 'Meeting invitation sent successfully',
                'email_id': result.get('id', None)
            }
            
        except Exception as e:
            logger.error(f"Error sending meeting invitation: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': f'Failed to send meeting invitation: {str(e)}'
            }
    
    async def combined_schedule_and_invite(
        self,
        title: str,
        description: str,
        start_time: datetime,
        duration_minutes: int,
        timezone: str,
        attendees: List[str],
        additional_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Schedule a meeting and send invitations in one step"""
        try:
            logger.info(f"Agent scheduling meeting and sending invitations: '{title}'")
            
            # First schedule the meeting
            meeting_result = await self.schedule_meeting(
                title=title,
                description=description,
                start_time=start_time,
                duration_minutes=duration_minutes,
                timezone=timezone,
                attendees=attendees,
                send_invites=True  # Google Calendar will send invites
            )
            
            if meeting_result.get('status') != 'success':
                logger.error(f"Failed to schedule meeting: {meeting_result.get('message')}")
                return meeting_result
            
            # If requested, send a custom email with the meeting details
            if additional_message:
                logger.info(f"Sending additional email for meeting with message: {additional_message[:100]}...")
                
                email_result = await self.send_meeting_invitation(
                    meeting_details=meeting_result.get('meeting', {}),
                    to=attendees,
                    additional_message=additional_message
                )
                
                meeting_result['email_status'] = email_result.get('status')
                meeting_result['email_message'] = email_result.get('message')
            
            return meeting_result
            
        except Exception as e:
            logger.error(f"Error in combined scheduling and invitation: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': f'Failed to schedule meeting and send invitations: {str(e)}'
            }