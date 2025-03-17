from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
import logging

from managers.connection_manager import ConnectionManager
from database.config import get_db
from services.vector_store.qdrant_service import QdrantService
from services.webrtc.manager import WebRTCManager

logger = logging.getLogger(__name__)

from config.settings import ALLOWED_ORIGINS, DEBUG, APP_PREFIX
# from routes.ai_routes_handlers import ai_router
# from routes.voice_routes_handlers import voice_router
from routes.healthcheck_handlers import healthcheck_router
from routes.webrtc_handlers import router as webrtc_router
# from routes.calendar_routes_handlers import calendar_router
# from routes.google_sheets_routes import router as google_sheets_router  
# from routes.websocket_handlers import router as websocket_router
from routes.admin_routes_handlers import router as admin_router
from routes.twilio_handlers import router as twilio_router

app = FastAPI(
    title="AI Backend",
    version="1.0.0",
    debug=DEBUG,
    description="AI Backend Service"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root route redirects to docs
@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

# Include routers
app.include_router(healthcheck_router, prefix=f"{APP_PREFIX}/health", tags=["Health"])
# app.include_router(ai_router, prefix=f"{APP_PREFIX}/ai", tags=["AI"])
# app.include_router(voice_router, prefix=f"{APP_PREFIX}/voice", tags=["Voice"])
app.include_router(webrtc_router, prefix=f"{APP_PREFIX}/webrtc", tags=["WebRTC"])
# app.include_router(calendar_router, prefix=f"{APP_PREFIX}/calendar", tags=["Calendar"])
# app.include_router(google_sheets_router, prefix=f"{APP_PREFIX}/google_sheets", tags=["Google Sheets"])
# app.include_router(websocket_router, prefix=f"{APP_PREFIX}/ws", tags=["websocket"])
app.include_router(admin_router, prefix=f"{APP_PREFIX}/admin", tags=["Admin"])
app.include_router(twilio_router, prefix=f"{APP_PREFIX}/twilio", tags=["Twilio"])




@app.on_event("startup")
async def startup_event():
    # Initialize connection manager
    db_session = next(get_db())
    
    # Initialize vector store
    vector_store = QdrantService()
    
    # Initialize connection manager
    connection_manager = ConnectionManager(db_session, vector_store)
    app.state.connection_manager = connection_manager
    
    # Initialize WebRTC manager
    webrtc_manager = WebRTCManager()
    webrtc_manager.connection_manager = connection_manager
    app.state.webrtc_manager = webrtc_manager
    app.state.response_cache = {}
    app.state.stream_sids = {} 
    app.state.call_mappings = {}
    app.state.client_call_mapping = {}  
    logger.info("Initialized shared application state")
    
    logger.info("Application initialized with connection and WebRTC managers")