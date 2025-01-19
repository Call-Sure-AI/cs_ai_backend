from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def ai_placeholder():
    """
    Placeholder route for AI-related operations.
    """
    return {"message": "AI routes are under construction."}
