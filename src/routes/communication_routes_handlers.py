# routes/communication_routes_handlers.py
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, EmailStr, Field
import logging
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import tempfile

from database.config import get_db
from database.models import Company, Agent
from services.communication.agent_communication import AgentCommunicationService
from config.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Pydantic models for request validation
class EmailRequest(BaseModel):
    company_id: str
    agent_id: str
    to: List[EmailStr]
    subject: str
    body: str
    cc: Optional[List[EmailStr]] = None
    bcc: Optional[List[EmailStr]] = None
    html_body: Optional[str] = None
    reply_to: Optional[EmailStr] = None

class MeetingRequest(BaseModel):
    company_id: str
    agent_id: str
    title: str
    description: str
    start_time: datetime
    duration_minutes: int
    timezone: str = Field(default="UTC")
    attendees: List[EmailStr]
    additional_message: Optional[str] = None

# Helper functions
async def get_communication_service(company_id: str, db: Session) -> AgentCommunicationService:
    """Get configured communication service for a company"""
    try:
        # Get company settings
        company = db.query(Company).filter_by(id=company_id).first()
        if not company:
            logger.error(f"Company not found: {company_id}")
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Check if Google API credentials are configured
        settings_dict = company.settings or {}
        logger.info(f"Company settings: {settings_dict.keys()}")
        
        google_config = settings_dict.get("google_api", {})
        
        # Check environment variable first
        service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not service_account_file:
            # If not in env, check if we have the default service account file
            if hasattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE") and settings.GOOGLE_SERVICE_ACCOUNT_FILE:
                service_account_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
                
            # If still not found, check if company has custom service account
            if not service_account_file or not os.path.isfile(service_account_file):
                service_account_data = google_config.get("service_account")
                if service_account_data:
                    # Save to a temporary file
                    fd, service_account_file = tempfile.mkstemp(suffix='.json')
                    os.close(fd)
                    
                    with open(service_account_file, "w") as f:
                        if isinstance(service_account_data, str):
                            f.write(service_account_data)
                        else:
                            json.dump(service_account_data, f)
                    
                    logger.info(f"Created temporary service account file: {service_account_file}")
                else:
                    logger.error("Google API service account not configured")
                    raise HTTPException(
                        status_code=400,
                        detail="Google API service account not configured"
                    )
        
        # Get sender email
        sender_email = google_config.get("sender_email")
        if not sender_email:
            sender_email = os.environ.get("GOOGLE_SENDER_EMAIL")
            
        if not sender_email:
            logger.error("Sender email not configured")
            raise HTTPException(
                status_code=400,
                detail="Sender email not configured"
            )
        
        # Get calendar ID
        calendar_id = google_config.get("calendar_id")
        if not calendar_id:
            calendar_id = os.environ.get("GOOGLE_CALENDAR_ID") or settings.GOOGLE_CALENDAR_ID
            
        if not calendar_id:
            logger.error("Calendar ID not configured")
            raise HTTPException(
                status_code=400,
                detail="Calendar ID not configured"
            )
        
        logger.info(f"Creating communication service with: {service_account_file}, {sender_email}, {calendar_id}")
        
        # Create and return the service
        return AgentCommunicationService(
            service_account_json=service_account_file,
            sender_email=sender_email,
            calendar_id=calendar_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating communication service: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create communication service: {str(e)}"
        )

@router.get("/communication/test/{company_id}")
async def test_communication(
    company_id: str,
    db: Session = Depends(get_db)
):
    """Test if communication services are properly configured for a company"""
    try:
        # Get company
        company = db.query(Company).filter_by(id=company_id).first()
        if not company:
            return {"status": "error", "message": "Company not found"}
        
        # Try to create the service
        service = await get_communication_service(company_id, db)
        
        # If we get here, it worked
        return {
            "status": "success", 
            "message": "Communication service configured correctly",
            "config": {
                "company_id": company_id,
                "company_name": company.name,
                "sender_email": service.sender_email,
                "calendar_id": service.calendar_id
            }
        }
    except HTTPException as e:
        return {"status": "error", "message": e.detail, "status_code": e.status_code}
    except Exception as e:
        logger.error(f"Error testing communication service: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# Email routes
@router.post("/agents/email")
async def send_email(
    request: EmailRequest = Body(...),
    db: Session = Depends(get_db)
):
    """Send an email on behalf of an agent"""
    try:
        # Validate agent exists
        agent = db.query(Agent).filter_by(
            id=request.agent_id,
            company_id=request.company_id,
            active=True
        ).first()
        
        if not agent:
            logger.error(f"Agent not found or inactive: {request.agent_id}")
            raise HTTPException(status_code=404, detail="Agent not found or inactive")
        
        logger.info(f"Sending email on behalf of agent {agent.name} ({agent.id})")
        
        # Get communication service
        service = await get_communication_service(request.company_id, db)
        
        # Send email
        result = await service.send_email(
            to=request.to,
            subject=request.subject,
            body=request.body,
            cc=request.cc,
            bcc=request.bcc,
            html_body=request.html_body,
            reply_to=request.reply_to
        )
        
        if result.get("status") == "error":
            logger.error(f"Error sending email: {result.get('message')}")
            raise HTTPException(status_code=500, detail=result.get("message"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email: {str(e)}"
        )

# Meeting routes
@router.post("/agents/meeting")
async def schedule_meeting(
    request: MeetingRequest = Body(...),
    db: Session = Depends(get_db)
):
    """Schedule a meeting with Google Meet on behalf of an agent"""
    try:
        # Validate agent exists
        agent = db.query(Agent).filter_by(
            id=request.agent_id,
            company_id=request.company_id,
            active=True
        ).first()
        
        if not agent:
            logger.error(f"Agent not found or inactive: {request.agent_id}")
            raise HTTPException(status_code=404, detail="Agent not found or inactive")
        
        logger.info(f"Scheduling meeting on behalf of agent {agent.name} ({agent.id})")
        
        # Get communication service
        service = await get_communication_service(request.company_id, db)
        
        # Schedule meeting and send invitations
        result = await service.combined_schedule_and_invite(
            title=request.title,
            description=request.description,
            start_time=request.start_time,
            duration_minutes=request.duration_minutes,
            timezone=request.timezone,
            attendees=request.attendees,
            additional_message=request.additional_message
        )
        
        if result.get("status") == "error":
            logger.error(f"Error scheduling meeting: {result.get('message')}")
            raise HTTPException(status_code=500, detail=result.get("message"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scheduling meeting: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to schedule meeting: {str(e)}"
        )