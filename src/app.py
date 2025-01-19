from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

# Local imports
from config.settings import ALLOWED_ORIGINS, DEBUG, APP_PREFIX
from routes import ai_routes, voice_routes, healthcheck
from middleware.error_handler import add_error_handlers
from middleware.auth_middleware import add_auth_middleware
from middleware.rate_limiter import add_rate_limiter

def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="AI Backend",
        version="1.0.0",
        debug=DEBUG,
        description="An AI Backend Service integrating GPT, TTS, STT, and other capabilities."
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add routes
    @app.get("/")
    async def root():
        return RedirectResponse(url="/docs")

    @app.get(APP_PREFIX)
    async def api_root():
        return {
            "name": "AI Backend API",
            "version": "1.0.0",
            "endpoints": {
                "health": f"{APP_PREFIX}/health",
                "ai": f"{APP_PREFIX}/ai",
                "voice": f"{APP_PREFIX}/voice",
                "documentation": "/docs"
            }
        }

    # Include routers
    app.include_router(healthcheck.router, prefix=f"{APP_PREFIX}/health", tags=["Health"])
    app.include_router(ai_routes.router, prefix=f"{APP_PREFIX}/ai", tags=["AI"])
    app.include_router(voice_routes.router, prefix=f"{APP_PREFIX}/voice", tags=["Voice"])

    # Add middleware
    add_error_handlers(app)
    add_auth_middleware(app)
    add_rate_limiter(app)

    if DEBUG:
        @app.middleware("http")
        async def log_request_response(request, call_next):
            print(f"Request: {request.method} {request.url}")
            response = await call_next(request)
            print(f"Response: {response.status_code}")
            return response

    return app

app = create_app()