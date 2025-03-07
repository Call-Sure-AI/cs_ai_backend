# services/calendar/google_meet_service.py
from typing import Dict, Any, Optional, List
import logging
import asyncio
import os
from datetime import datetime, timedelta
from services.calendar.async_google_calendar import AsyncGoogleCalendar
from services.calendar.types import (
    CalendarConfig,
    AppointmentData,
    EventOptions,
)

logger = logging.getLogger(__name__)

class GoogleMeetService:
    def __init__(self, calendar_service: AsyncGoogleCalendar):
        """Initialize Google Meet integration with an existing calendar service"""
        self.calendar_service = calendar_service
    
    async def create_meet_event(
        self,
        title: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        attendees: List[str],
        send_invites: bool = True,
        options: Optional[EventOptions] = None
    ) -> Dict[str, Any]:
        """Create a Google Calendar event with Google Meet link"""
        try:
            # Ensure the calendar service is set up
            await self.calendar_service.setup()
            
            # Log event details
            logger.info(f"Creating Google Meet event: '{title}' at {start_time}")
            
            # Create appointment data
            appointment_data = AppointmentData(
                title=title,
                description=description,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                attendees=attendees
            )
            
            # Set up event options with Google Meet conferencing
            if options is None:
                options = EventOptions(
                    include_attendees=True,
                    send_updates="all" if send_invites else "none",
                    reminders_enabled=True,
                    add_attendees_to_description=True
                )
            
            # Create a new event with the calendar service
            event = {
                'summary': appointment_data.title,
                'description': appointment_data.description,
                'start': {
                    'dateTime': appointment_data.start_time.isoformat(),
                    'timeZone': appointment_data.timezone,
                },
                'end': {
                    'dateTime': appointment_data.end_time.isoformat(),
                    'timeZone': appointment_data.timezone,
                },
                # Add Google Meet conferencing
                'conferenceData': {
                    'createRequest': {
                        'requestId': f'meet-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                }
            }
            
            if options.include_attendees:
                event['attendees'] = [{'email': attendee} for attendee in appointment_data.attendees]
            
            if options.reminders_enabled:
                if options.custom_reminders:
                    event['reminders'] = {
                        'useDefault': False,
                        'overrides': options.custom_reminders
                    }
                else:
                    event['reminders'] = {'useDefault': True}
            
            create_kwargs = {
                'calendarId': self.calendar_service.config.calendar_id,
                'body': event,
                'conferenceDataVersion': 1  # Enable conferencing
            }
            
            if options.send_updates:
                create_kwargs['sendUpdates'] = options.send_updates
            
            # Execute the API request
            event_request = self.calendar_service.service.events().insert(**create_kwargs)
            created_event = await asyncio.to_thread(event_request.execute)
            
            # Extract the meeting details
            meet_info = None
            if 'conferenceData' in created_event and 'entryPoints' in created_event['conferenceData']:
                for entry_point in created_event['conferenceData']['entryPoints']:
                    if entry_point['entryPointType'] == 'video':
                        meet_info = {
                            'meet_link': entry_point['uri'],
                            'event_id': created_event['id'],
                            'html_link': created_event['htmlLink']
                        }
                        break
            
            if not meet_info:
                logger.warning("Google Meet link not found in created event")
                
            logger.info(f"Successfully created event with Google Meet: {created_event.get('id')}")
            
            return {
                'event': created_event,
                'meet_info': meet_info
            }
                
        except Exception as e:
            logger.error(f"Error creating event with Google Meet: {e}", exc_info=True)
            raise
    
    async def get_meet_link_details(self, event_id: str) -> Dict[str, Any]:
        """Get Google Meet details for an existing event"""
        try:
            await self.calendar_service.setup()
            
            # Get the event details
            event_request = self.calendar_service.service.events().get(
                calendarId=self.calendar_service.config.calendar_id,
                eventId=event_id
            )
            event = await asyncio.to_thread(event_request.execute)
            
            # Extract the meeting details
            meet_info = None
            if 'conferenceData' in event and 'entryPoints' in event['conferenceData']:
                for entry_point in event['conferenceData']['entryPoints']:
                    if entry_point['entryPointType'] == 'video':
                        meet_info = {
                            'meet_link': entry_point['uri'],
                            'event_id': event['id'],
                            'html_link': event['htmlLink']
                        }
                        break
            
            if not meet_info:
                logger.warning(f"Google Meet link not found for event {event_id}")
                
            return {
                'event': event,
                'meet_info': meet_info
            }
                
        except Exception as e:
            logger.error(f"Error getting Google Meet details: {e}", exc_info=True)
            raise