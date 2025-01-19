from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from config.settings import ALLOWED_ORIGINS, DEBUG, APP_PREFIX
from routes.ai_routes_handlers import ai_router
from routes.voice_routes_handlers import voice_router
from routes.healthcheck_handlers import healthcheck_router

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
app.include_router(ai_router, prefix=f"{APP_PREFIX}/ai", tags=["AI"])
app.include_router(voice_router, prefix=f"{APP_PREFIX}/voice", tags=["Voice"])