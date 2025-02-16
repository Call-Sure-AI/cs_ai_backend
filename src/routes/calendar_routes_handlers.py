from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List, Dict
from pydantic import BaseModel
from datetime import datetime, timedelta
import pytz
import logging
from src.services.calendar.microsoft_calendar import MicrosoftCalendar, MicrosoftConfig
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

async def get_calendar():
    """Dependency to get calendar instance"""
    config = MicrosoftConfig(
        client_id=settings.MICROSOFT_CLIENT_ID,
        token_store_path=settings.CALENDAR_TOKEN_STORE_PATH,
        timezone=settings.DEFAULT_TIMEZONE
    )
    calendar = MicrosoftCalendar(config)
    try:
        yield calendar
    finally:
        await calendar.cleanup()

@calendar_router.post("/events/", response_model=EventResponse)
async def create_event(
    request: EventRequest,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """Create a new calendar event"""
    try:
        # Parse and validate times
        try:
            start_time = datetime.fromisoformat(request.start_time)
            if request.end_time:
                end_time = datetime.fromisoformat(request.end_time)
            else:
                end_time = start_time + timedelta(minutes=request.duration_minutes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid datetime format: {str(e)}")

        event = await calendar.create_event(
            title=request.title,
            description=request.description or "",
            start_time=start_time,
            end_time=end_time,
            attendees=request.attendees
        )
        
        return EventResponse(**event)
        
    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@calendar_router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """Get event details by ID"""
    try:
        event = await calendar.get_event(event_id)
        return EventResponse(**event)
    except Exception as e:
        logger.error(f"Error getting event: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

@calendar_router.put("/events/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    request: EventRequest,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """Update an existing event"""
    try:
        # Parse times if provided
        start_time = None
        end_time = None
        if request.start_time:
            start_time = datetime.fromisoformat(request.start_time)
        if request.end_time:
            end_time = datetime.fromisoformat(request.end_time)
        elif request.start_time and request.duration_minutes:
            end_time = start_time + timedelta(minutes=request.duration_minutes)

        event = await calendar.update_event(
            event_id=event_id,
            title=request.title,
            description=request.description,
            start_time=start_time,
            end_time=end_time,
            attendees=request.attendees
        )
        
        return EventResponse(**event)
        
    except Exception as e:
        logger.error(f"Error updating event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@calendar_router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """Delete an event"""
    try:
        success = await calendar.delete_event(event_id)
        if success:
            return {"message": "Event deleted successfully"}
        raise HTTPException(status_code=500, detail="Failed to delete event")
    except Exception as e:
        logger.error(f"Error deleting event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@calendar_router.get("/events/", response_model=List[EventResponse])
async def list_events(
    start_time: str,
    end_time: str,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """List events between start and end time"""
    try:
        try:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid datetime format: {str(e)}")

        events = await calendar.get_calendar_events(start, end)
        return [EventResponse(**event) for event in events]
        
    except Exception as e:
        logger.error(f"Error listing events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@calendar_router.post("/check-availability", response_model=AvailabilityResponse)
async def check_availability(
    request: EventRequest,
    calendar: MicrosoftCalendar = Depends(get_calendar)
):
    """Check availability for a time slot"""
    try:
        # Parse times
        start_time = datetime.fromisoformat(request.start_time)
        if request.end_time:
            end_time = datetime.fromisoformat(request.end_time)
        else:
            end_time = start_time + timedelta(minutes=request.duration_minutes)

        # Get events for the time period
        events = await calendar.get_calendar_events(start_time, end_time)
        
        if not events:
            # Time slot is available
            return AvailabilityResponse(
                is_available=True,
                message="Time slot is available"
            )
        else:
            # Find alternative slots
            alternative_start = start_time
            alternative_end = alternative_start + timedelta(days=7)
            all_events = await calendar.get_calendar_events(alternative_start, alternative_end)
            
            # Find gaps between events
            available_slots = []
            current_time = alternative_start
            
            for event in all_events:
                event_start = datetime.fromisoformat(event['start'])
                if current_time + timedelta(minutes=request.duration_minutes) <= event_start:
                    available_slots.append({
                        'start': current_time.isoformat(),
                        'end': (current_time + timedelta(minutes=request.duration_minutes)).isoformat()
                    })
                current_time = datetime.fromisoformat(event['end'])
            
            return AvailabilityResponse(
                is_available=False,
                message="Time slot is not available",
                available_slots=available_slots[:5]  # Return top 5 alternatives
            )
            
    except Exception as e:
        logger.error(f"Error checking availability: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))