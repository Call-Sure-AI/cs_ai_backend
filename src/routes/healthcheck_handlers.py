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
from services.rag.rag_service import RAGService
# from services.vector_store.chroma_service import VectorStore
from services.vector_store.qdrant_service import QdrantService
# from services.calendar.calendar_service import CalendarConfig, CalendarIntegration, CalendarType
from services.calendar.async_microsoft_calendar import MicrosoftCalendar, MicrosoftConfig
from datetime import datetime, timedelta
import pytz

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
        "vector_store": "operational",
        "calendar_services": {  # Changed to nested structure for multiple calendar providers
            "google": "operational",
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
    except Exception as e:
        logger.error(f"Redis healthcheck failed: {str(e)}")
        status["redis"] = "disconnected"
        status["status"] = "degraded"

    # Add data service checks
    try:
        document_loader = DocumentLoader()
        if not document_loader.SUPPORTED_EXTENSIONS:
            status["data_services"] = "degraded"
            status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Data service healthcheck failed: {str(e)}")
        status["data_services"] = "unavailable"
        status["status"] = "degraded"

    # Check Qdrant connection
    try:
        qdrant_service = QdrantService()
        qdrant_service.client.get_collections()
    except Exception as e:
        logger.error(f"Qdrant healthcheck failed: {str(e)}")
        status["vector_store"] = "disconnected"
        status["status"] = "degraded"

    # Check RAG service
    try:
        rag = RAGService()
        await rag.verify_embeddings("test_company")
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
        await ms_calendar.setup()
    except Exception as e:
        logger.error(f"Microsoft Calendar service healthcheck failed: {str(e)}")
        status["calendar_services"]["microsoft"] = "degraded"
        status["status"] = "degraded"

    return status