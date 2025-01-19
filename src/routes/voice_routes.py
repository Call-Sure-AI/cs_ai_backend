from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def voice_placeholder():
    """
    Placeholder route for voice-related operations.
    """
    return {"message": "Voice routes are under construction."}
