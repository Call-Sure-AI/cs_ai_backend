from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from src.routes import healthcheck, ai_routes, voice_routes

# Initialize the FastAPI app
# Initialize the FastAPI app
app = FastAPI(title="AI Backend", version="1.0.0", debug=DEBUG)

# Middleware for CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(healthcheck.router, prefix="/health", tags=["Health"])
app.include_router(ai_routes.router, prefix="/api/ai", tags=["AI"])
app.include_router(voice_routes.router, prefix="/api/voice", tags=["Voice"])

"""
Creates the FastAPI instance.
Loads middleware for error handling, authentication, and CORS.
Includes basic routes like healthcheck

Notes:
This file itself doesn’t require concurrency since it initializes the FastAPI app. 
Concurrency will be managed by the event loop when the app is deployed with Uvicorn
or another ASGI server.
"""