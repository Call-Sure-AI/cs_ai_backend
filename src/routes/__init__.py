# src/routes/__init__.py
from fastapi import APIRouter

# Initialize the main router
router = APIRouter()

# Import and include route handlers
from .ai_routes_handlers import ai_router
from .voice_routes_handlers import voice_router
from .healthcheck_handlers import healthcheck_router
from .google_sheets_routes import router as google_sheets_router  # ✅ Correct import

# Register routes
router.include_router(healthcheck_router, prefix="/health", tags=["Health"])
router.include_router(ai_router, prefix="/ai", tags=["AI"])
router.include_router(voice_router, prefix="/voice", tags=["Voice"])
router.include_router(google_sheets_router, prefix="/google_sheets", tags=["Google Sheets"])  # ✅ Correctly include Google Sheets API
