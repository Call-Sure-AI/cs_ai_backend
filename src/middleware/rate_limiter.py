from fastapi import FastAPI, Request
from config.settings import ENABLE_RATE_LIMITING, RATE_LIMIT_TTL, RATE_LIMIT_THRESHOLD

def add_rate_limiter(app: FastAPI):
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if not ENABLE_RATE_LIMITING:
            return await call_next(request)
        # Add your rate limiting logic here
        return await call_next(request)