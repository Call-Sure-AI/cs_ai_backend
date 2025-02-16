from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from websockets.exceptions import WebSocketException
import logging
from qdrant_client.http import exceptions as qdrant_exceptions
from langchain.errors import LangChainError
from O365.utils.errors import TokenExpiredError, AuthenticationError
import logging
from google.auth.exceptions import RefreshError
from google.api_core import exceptions as google_exceptions
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

def add_error_handlers(app: FastAPI):
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Global error: {str(exc)}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)}
        )
        
    @app.exception_handler(WebSocketException)
    async def websocket_exception_handler(request: Request, exc: WebSocketException):
        logger.error(f"WebSocket error: {str(exc)}")
        return JSONResponse(
            status_code=1011,  # WebSocket Internal Error
            content={"detail": "WebSocket error occurred"}
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)}
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)}
        )

    @app.exception_handler(qdrant_exceptions.UnexpectedResponse)
    async def qdrant_error_handler(request: Request, exc: qdrant_exceptions.UnexpectedResponse):
        return JSONResponse(
            status_code=500,
            content={"detail": "Vector store operation failed", "error": str(exc)}
        )
    
    @app.exception_handler(ConnectionError)
    async def connection_error_handler(request: Request, exc: ConnectionError):
        return JSONResponse(
            status_code=503,
            content={"detail": "Service connection failed", "error": str(exc)}
        )

    @app.exception_handler(LangChainError)
    async def langchain_error_handler(request: Request, exc: LangChainError):
        return JSONResponse(
            status_code=500,
            content={"detail": "RAG operation failed", "error": str(exc)}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)}
        )

    # Add calendar-specific error handlers
    @app.exception_handler(TokenExpiredError)
    async def token_expired_handler(request: Request, exc: TokenExpiredError):
        logger.error(f"Token expired: {str(exc)}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Calendar authentication expired. Please reauthenticate."}
        )

    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        logger.error(f"Authentication error: {str(exc)}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Calendar authentication failed."}
        )

    @app.exception_handler(RefreshError)
    async def google_refresh_error_handler(request: Request, exc: RefreshError):
        logger.error(f"Google token refresh error: {str(exc)}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Google Calendar authentication needs to be refreshed."}
        )

    @app.exception_handler(google_exceptions.PermissionDenied)
    async def google_permission_error_handler(request: Request, exc: google_exceptions.PermissionDenied):
        logger.error(f"Google permission error: {str(exc)}")
        return JSONResponse(
            status_code=403,
            content={"detail": "Insufficient permissions for Google Calendar operation."}
        )

    @app.exception_handler(RequestException)
    async def request_error_handler(request: Request, exc: RequestException):
        logger.error(f"Calendar API request error: {str(exc)}")
        return JSONResponse(
            status_code=503,
            content={"detail": "Calendar service temporarily unavailable."}
        )

    @app.exception_handler(WebSocketException)
    async def websocket_exception_handler(request: Request, exc: WebSocketException):
        logger.error(f"WebSocket error: {str(exc)}")
        return JSONResponse(
            status_code=1011,  # WebSocket Internal Error
            content={"detail": "Calendar WebSocket connection error occurred"}
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        if "Calendar" in str(exc):  # Only handle calendar-related value errors
            logger.error(f"Calendar value error: {str(exc)}")
            return JSONResponse(
                status_code=400,
                content={"detail": str(exc)}
            )
        raise exc