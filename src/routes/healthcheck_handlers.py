from fastapi import APIRouter, HTTPException
from typing import Dict
import redis
from config.settings import (
    REDIS_HOST, 
    REDIS_PORT, 
    GOOGLE_SERVICE_ACCOUNT_FILE, 
    GOOGLE_CALENDAR_ID,
    MICROSOFT_CLIENT_ID
)
import logging
import asyncio
from services.rag.rag_service import RAGService
from services.vector_store.qdrant_service import QdrantService
from services.calendar.async_microsoft_calendar import MicrosoftCalendar, MicrosoftConfig
from services.dataloaders.data_loaders import DocumentLoader
from datetime import datetime, timedelta
import pytz

# from services.vector_store.chroma_service import VectorStore
# from services.calendar.calendar_service import CalendarConfig, CalendarIntegration, CalendarType

logger = logging.getLogger(__name__)
healthcheck_router = APIRouter()

@healthcheck_router.get("")
async def health_check() -> Dict:
    status = {
        "status": "healthy",
        "database": "connected",
        "ai_services": "operational",
        "storage": "available",
        "redis": "connected",
        "data_services": "operational",  # Add this line
        "vector_store": "connected",
        "rag_service": "operational",
        "calendar_services": {  # Changed to nested structure for multiple calendar providers
            "google": "not_configured",
            "microsoft": "operational"
        }
    }
    
    # Check Redis connection
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            socket_timeout=2
        )
        redis_client.ping()
    except redis.ConnectionError as e:
        logger.error(f"Redis connection error: {str(e)}")
        status["redis"] = "disconnected"
        status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Redis healthcheck failed: {str(e)}")
        status["redis"] = "unknown_error"
        status["status"] = "degraded"

    # Add data service checks
    try:
        document_loader = DocumentLoader()
        if not hasattr(document_loader, 'SUPPORTED_EXTENSIONS') or not document_loader.SUPPORTED_EXTENSIONS:
            status["data_services"] = "degraded"
            status["status"] = "degraded"
    except ImportError as e:
        logger.error(f"Data service import error: {str(e)}")
        status["data_services"] = "import_error"
        status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Data service healthcheck failed: {str(e)}")
        status["data_services"] = "unavailable"
        status["status"] = "degraded"

    # Check Qdrant connection
    try:
        qdrant_service = QdrantService()
        # Add timeout for operation
        collections = await asyncio.wait_for(
            asyncio.to_thread(qdrant_service.client.get_collections),
            timeout=5.0
        )
        logger.info(f"Qdrant collections: {collections}")
    except asyncio.TimeoutError:
        logger.error("Qdrant connection timeout")
        status["vector_store"] = "timeout"
        status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Qdrant healthcheck failed: {str(e)}")
        status["vector_store"] = "disconnected"
        status["status"] = "degraded"

    # Check RAG service
    try:
        rag = RAGService()
        # Add timeout for verification
        await asyncio.wait_for(
            rag.verify_embeddings("test_company"),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.error("RAG service timeout")
        status["rag_service"] = "timeout"
        status["status"] = "degraded"
    except Exception as e:
        logger.error(f"RAG service healthcheck failed: {str(e)}")
        status["rag_service"] = "degraded"
        status["status"] = "degraded"

    # Check vector store
    # try:
    #     vector_store = VectorStore()
    #     # Try to create a test collection
    #     await vector_store.create_company_collection("health_check")
    # except Exception as e:
    #     logger.error(f"Vector store healthcheck failed: {str(e)}")
    #     status["vector_store"] = "degraded"
    #     status["status"] = "degraded"

    # Check Google Calendar service
    # try:
    #     config = CalendarConfig(
    #         service_account_json=GOOGLE_SERVICE_ACCOUNT_FILE,
    #         calendar_id=GOOGLE_CALENDAR_ID
    #     )
    #     calendar = CalendarIntegration(config)
    #     await calendar.check_availability(
    #         datetime.now(pytz.UTC),
    #         datetime.now(pytz.UTC) + timedelta(minutes=30),
    #         CalendarType.GOOGLE
    #     )
    # except Exception as e:
    #     logger.error(f"Google Calendar service healthcheck failed: {str(e)}")
    #     status["calendar_services"]["google"] = "degraded"
        # status["status"] = "degraded"

    # Check Microsoft Calendar service
    try:
        ms_config = MicrosoftConfig(
            client_id=MICROSOFT_CLIENT_ID,
        )
        ms_calendar = MicrosoftCalendar(ms_config)
        # Add timeout for setup
        await asyncio.wait_for(
            ms_calendar.setup(),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.error("Microsoft Calendar connection timeout")
        status["calendar_services"]["microsoft"] = "timeout"
        status["status"] = "degraded"
    except ImportError as e:
        logger.error(f"Microsoft Calendar import error: {str(e)}")
        status["calendar_services"]["microsoft"] = "import_error"
        status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Microsoft Calendar healthcheck failed: {str(e)}")
        status["calendar_services"]["microsoft"] = "degraded"
        status["status"] = "degraded"

    # Set Google Calendar as "not_configured" since it's not being checked
    status["calendar_services"]["google"] = "not_configured"

    return status

"""
Looking at the healthcheck_router code, I've identified several issues:
- Missing import for DocumentLoader - The code tries to use DocumentLoader() but doesn't import it. This would cause a NameError when trying to run the healthcheck.
- Duplicate key in the status dictionary - "vector_store" appears twice in the status dictionary, which means the second occurrence will overwrite the first one.
- Commented-out code that's being referenced - There are multiple commented-out imports and code blocks that make references to them, which could cause confusion about what's supposed to be active.
- Inconsistent error handling - For the Google Calendar service check, there's a commented line that sets the overall status to "degraded", but it's commented out while the Microsoft Calendar service does set it.
- No clean separation between initialization and actual health checks - For example, creating a QdrantService() instance doesn't guarantee it's properly configured or functional beyond just instantiating.
- No timeout handling for the RAG service check - The rag.verify_embeddings() call doesn't have an explicit timeout, which could cause the health check to hang indefinitely if there's a connection issue.
- Potentially uncaught ImportError - If any import fails (like the Redis module), it would throw an error before the function is even defined.
- Insufficient error specificity - The error handling catches all exceptions, but different types of failures (like network errors vs. authentication errors) should trigger different status messages.

Changes made by Sai
- Fixed the missing import for DocumentLoader
- Removed the duplicate vector_store key in the status dictionary
- Added proper timeouts to prevent hanging health checks
- Used more specific exception types for better error classification
- Added attribute checking with hasattr() before accessing attributes
- Set Google Calendar status as "not_configured" since it's not being checked
- Added more logging to help with debugging
- Used asyncio.to_thread() for potentially blocking operations
- Added proper imports
- Added better error handling with specific exception types
- Added timeouts to prevent hanging
- Fixed the Redis connection error handling
- Added checks for the existence of attributes
- Set correct status for the Google Calendar service
"""