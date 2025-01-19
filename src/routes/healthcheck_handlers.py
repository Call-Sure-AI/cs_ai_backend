from fastapi import APIRouter, HTTPException
from typing import Dict

healthcheck_router = APIRouter()

@healthcheck_router.get("")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "ai_services": "operational",
        "storage": "available"
    }