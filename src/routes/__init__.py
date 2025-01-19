# src/routes/__init__.py

# Export routers for easier access
from .ai_routes import router as ai_router
from .voice_routes import router as voice_router
from .healthcheck import router as health_router
