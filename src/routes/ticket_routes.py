from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from database.config import get_db
from services.ticket_service import AutoTicketService
from pydantic import BaseModel

router = APIRouter()

class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    note: Optional[str] = None

class TicketNoteRequest(BaseModel):
    content: str
    is_internal: bool = True

@router.get("/companies/{company_id}/tickets")
async def get_company_tickets(
    company_id: str,
    status: Optional[List[str]] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get tickets for a company with filtering"""
    ticket_service = AutoTicketService(db)
    tickets, total_count = await ticket_service.get_tickets_for_company(
        company_id, status, limit, offset
    )
    
    return {
        "tickets": tickets,
        "total_count": total_count,
        "limit": limit,
        "offset": offset
    }

@router.get("/companies/{company_id}/tickets/{ticket_id}")
async def get_ticket_details(
    company_id: str,
    ticket_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed ticket information"""
    ticket_service = AutoTicketService(db)
    ticket_details = await ticket_service.get_ticket_details(ticket_id, company_id)
    
    if not ticket_details:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return ticket_details

@router.patch("/companies/{company_id}/tickets/{ticket_id}")
async def update_ticket(
    company_id: str,
    ticket_id: str,
    update_data: TicketUpdateRequest,
    updated_by: str = "user@example.com",  # Should come from auth
    db: Session = Depends(get_db)
):
    """Update ticket status, assignment, etc."""
    ticket_service = AutoTicketService(db)
    
    if update_data.status:
        success = await ticket_service.update_ticket_status(
            ticket_id, update_data.status, company_id, updated_by, update_data.note
        )
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update ticket")
    
    return {"message": "Ticket updated successfully"}

@router.post("/companies/{company_id}/tickets/{ticket_id}/notes")
async def add_ticket_note(
    company_id: str,
    ticket_id: str,
    note_data: TicketNoteRequest,
    author: str = "user@example.com",  # Should come from auth
    db: Session = Depends(get_db)
):
    """Add a note to a ticket"""
    ticket_service = AutoTicketService(db)
    
    success = await ticket_service.add_ticket_note(
        ticket_id, note_data.content, author, company_id, note_data.is_internal
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add note")
    
    return {"message": "Note added successfully"}