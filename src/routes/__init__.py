# src/routes/__init__.py
from fastapi import APIRouter

# Initialize routers
ai_routes = APIRouter()
voice_routes = APIRouter()
healthcheck = APIRouter()

# Import route definitions
from . import ai_routes_handlers
from . import voice_routes_handlers
from . import healthcheck_handlers