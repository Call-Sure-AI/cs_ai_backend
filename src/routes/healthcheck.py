from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def health_check():
    """
    Health check endpoint.
    Returns a 200 status if the service is up.
    """
    return {"status": "healthy"}
