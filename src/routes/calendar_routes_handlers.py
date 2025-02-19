from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List, Dict, Union
from pydantic import BaseModel
from datetime import datetime, timedelta
import pytz
import logging
import asyncio
from src.services.calendar.async_microsoft_calendar import MicrosoftCalendar, MicrosoftConfig
from src.services.calendar.async_google_calendar import AsyncGoogleCalendar
from src.services.calendar.calendar_integration import CalendarIntegration
from src.services.calendar.types import (
    CalendarConfig, 
    CalendarType,
    EventOptions,
    AppointmentData,
    AvailabilityOptions
)
from src.config.settings import settings

logger = logging.getLogger(__name__)
calendar_router = APIRouter()

class EventRequest(BaseModel):
    """Event request model"""
    start_time: str
    end_time: Optional[str] = None
    timezone: Optional[str] = "UTC"
    title: str
    description: Optional[str] = ""
    attendees: List[str]
    duration_minutes: Optional[int] = 60
    calendar_type: Optional[str] = "microsoft"  # "microsoft", "google", or "calendly"

class EventResponse(BaseModel):
    """Event response model"""
    id: str
    subject: str
    start: str
    end: str
    attendees: List[str]

class AvailabilityResponse(BaseModel):
    """Availability response model"""
    is_available: bool
    message: str
    available_slots: Optional[List[Dict]] = None
    event_id: Optional[str] = None

def handle_calendar_exception(func):
    """Decorator to handle exceptions in calendar routes"""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Validation error in {func.__name__}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    return wrapper

async def get_calendar(calendar_type: str = "microsoft"):
    """Dependency to get calendar instance"""
    if calendar_type == "microsoft":
        config = MicrosoftConfig(
            client_id=settings.MICROSOFT_CLIENT_ID,
            token_store_path=settings.CALENDAR_TOKEN_STORE_PATH,
            timezone=settings.DEFAULT_TIMEZONE
        )
        calendar = MicrosoftCalendar(config)
    elif calendar_type == "google":
        config = CalendarConfig(
            service_account_json=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
            calendar_id=settings.GOOGLE_CALENDAR_ID,
            timezone=settings.DEFAULT_TIMEZONE,
            token_store_path=settings.CALENDAR_TOKEN_STORE_PATH
        )
        calendar = AsyncGoogleCalendar(config)
    elif calendar_type == "calendly":
        config = CalendarConfig(
            calendly_token=settings.CALENDLY_TOKEN,
            timezone=settings.DEFAULT_TIMEZONE,
            token_store_path=settings.CALENDAR_TOKEN_STORE_PATH
        )
        calendar = CalendarIntegration(config)
    else:
        raise HTTPException(status_code=400, detail="Invalid calendar type")
        
    try:
        if hasattr(calendar, "setup"):
            await calendar.setup()
        yield calendar
    finally:
        if hasattr(calendar, "cleanup"):
            await (calendar.cleanup() if asyncio.iscoroutinefunction(calendar.cleanup) else asyncio.to_thread(calendar.cleanup))


@calendar_router.post("/events/", response_model=EventResponse)
@handle_calendar_exception
async def create_event(
    request: EventRequest,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    start_time = datetime.fromisoformat(request.start_time)
    end_time = datetime.fromisoformat(request.end_time) if request.end_time else start_time + timedelta(minutes=request.duration_minutes)
    
    event_options = EventOptions(
        include_attendees=True,
        send_updates="all",
        add_attendees_to_description=True
    )

    if isinstance(calendar, MicrosoftCalendar):
        event = await calendar.create_event(
            title=request.title,
            description=request.description or "",
            start_time=start_time,
            end_time=end_time,
            attendees=request.attendees
        )
    elif isinstance(calendar, AsyncGoogleCalendar):
        appointment = AppointmentData(
            start_time=start_time,
            end_time=end_time,
            title=request.title,
            description=request.description or "",
            attendees=request.attendees,
            timezone=request.timezone
        )
        event = await calendar.create_event(appointment, event_options)
    elif isinstance(calendar, CalendarIntegration):
        appointment = AppointmentData(
            start_time=start_time,
            end_time=end_time,
            title=request.title,
            description=request.description or "",
            attendees=request.attendees,
            timezone=request.timezone
        )
        event = calendar.create_event(
            appointment_data=appointment,
            calendar_type=request.calendar_type,
            options=event_options
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid calendar type")

    return EventResponse(
        id=event.get('id') or event.get('object_id') or "UNKNOWN_EVENT_ID",
        subject=event.get('subject') or event.get('summary'),
        start=event.get('start'),
        end=event.get('end'),
        attendees=[a.get('email') if isinstance(a, dict) else a for a in event.get('attendees', [])]
    )

@calendar_router.get("/events/{event_id}", response_model=EventResponse)
@handle_calendar_exception
async def get_event(
    event_id: str,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    """Get event details by ID"""
    if isinstance(calendar, (MicrosoftCalendar, AsyncGoogleCalendar)):
        event = await calendar.get_event(event_id)
    elif isinstance(calendar, CalendarIntegration):
        event = calendar.get_event(event_id)  # Calendly API uses sync calls
    else:
        raise HTTPException(status_code=400, detail="Invalid calendar type")

    return EventResponse(**(event or {}))

@calendar_router.put("/events/{event_id}", response_model=EventResponse)
@handle_calendar_exception
async def update_event(
    event_id: str,
    request: EventRequest,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    """Update an existing event"""
    start_time = datetime.fromisoformat(request.start_time) if request.start_time else None
    end_time = datetime.fromisoformat(request.end_time) if request.end_time else (
        start_time + timedelta(minutes=request.duration_minutes) if start_time else None
    )

    if isinstance(calendar, MicrosoftCalendar):
        event = await calendar.update_event(
            event_id=event_id,
            title=request.title,
            description=request.description,
            start_time=start_time,
            end_time=end_time,
            attendees=request.attendees
        )
    elif isinstance(calendar, AsyncGoogleCalendar):
        appointment = AppointmentData(
            start_time=start_time,
            end_time=end_time,
            title=request.title,
            description=request.description or "",
            attendees=request.attendees,
            timezone=request.timezone
        )
        event = await calendar.update_event(event_id, appointment)
    else:
        # CalendarIntegration (sync) for Calendly
        appointment = AppointmentData(
            start_time=start_time,
            end_time=end_time,
            title=request.title,
            description=request.description or "",
            attendees=request.attendees,
            timezone=request.timezone
        )
        event = calendar.update_appointment(
            event_id=event_id,
            calendar_type=request.calendar_type,
            appointment_data=appointment
        )
    
    return EventResponse(**event)

@calendar_router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    """Delete an event"""
    try:
        if isinstance(calendar, MicrosoftCalendar):
            success = await calendar.delete_event(event_id)
        else:
            success = calendar.cancel_appointment(
                event_id=event_id,
                calendar_type=request.calendar_type
            )
            
        if success:
            return {"message": "Event deleted successfully"}
        raise HTTPException(status_code=500, detail="Failed to delete event")
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@calendar_router.get("/events/", response_model=List[EventResponse])
@handle_calendar_exception
async def list_events(
    start_time: str,
    end_time: str,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    """List events between start and end time"""
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)

    if isinstance(calendar, (MicrosoftCalendar, AsyncGoogleCalendar)):
        events = await calendar.get_calendar_events(start, end)
    else:
        # CalendarIntegration for Calendly
        events = calendar.list_events(start, end)
        
    return [EventResponse(**event) for event in events]

@calendar_router.post("/check-availability", response_model=AvailabilityResponse)
@handle_calendar_exception
async def check_availability(
    request: EventRequest,
    calendar: Union[MicrosoftCalendar, AsyncGoogleCalendar, CalendarIntegration] = Depends(get_calendar)
):
    """Check availability for a time slot"""
    start_time = datetime.fromisoformat(request.start_time)
    end_time = datetime.fromisoformat(request.end_time) if request.end_time else (
        start_time + timedelta(minutes=request.duration_minutes)
    )

    # Use native check_availability methods
    if isinstance(calendar, (MicrosoftCalendar, AsyncGoogleCalendar)):
        is_available = await calendar.check_availability(start_time, end_time)
    else:
        # CalendarIntegration for Calendly
        is_available = calendar.check_availability(
            start_time=start_time,
            end_time=end_time,
            calendar_type=request.calendar_type
        )
    
    if is_available:
        return AvailabilityResponse(
            is_available=True,
            message="Time slot is available"
        )

    availability_options = AvailabilityOptions(
        working_hours={
            'monday': {'start': '09:00', 'end': '17:00'},
            'tuesday': {'start': '09:00', 'end': '17:00'},
            'wednesday': {'start': '09:00', 'end': '17:00'},
            'thursday': {'start': '09:00', 'end': '17:00'},
            'friday': {'start': '09:00', 'end': '17:00'}
        },
        buffer_minutes=15,
        timezone=request.timezone
    )

    if isinstance(calendar, (MicrosoftCalendar, AsyncGoogleCalendar)):
        alternative_slots = await calendar.get_availability(
            start_date=start_time,
            end_date=start_time + timedelta(days=7),
            options=availability_options,
            duration_minutes=request.duration_minutes
        )
    else:
        alternative_slots = calendar.get_availability(
            start_date=start_time,
            end_date=start_time + timedelta(days=7),
            calendar_type=request.calendar_type,
            options=availability_options,
            duration_minutes=request.duration_minutes
        )
    
    return AvailabilityResponse(
        is_available=False,
        message="Time slot is not available",
        available_slots=[{
            'start': slot['start'].isoformat() if isinstance(slot['start'], datetime) else slot['start'],
            'end': slot['end'].isoformat() if isinstance(slot['end'], datetime) else slot['end']
        } for slot in alternative_slots[:5]]
    )