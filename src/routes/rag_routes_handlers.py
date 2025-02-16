from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Dict, Optional, Any
from src.services.rag.rag_service import RAGService
import logging
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
rag_router = APIRouter()
rag_service = RAGService()

@rag_router.post("/documents/{company_id}")
async def add_documents(
    company_id: str,
    documents: List[Dict[str, Any]],
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add documents to the RAG system"""
    try:
        success = await rag_service.add_documents(company_id, documents, agent_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add documents")
        return {"status": "success", "documents_count": len(documents)}
    except Exception as e:
        logger.error(f"Error adding documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@rag_router.delete("/documents/{company_id}/{agent_id}")
async def delete_agent_documents(
    company_id: str,
    agent_id: str
) -> Dict[str, str]:
    """Delete all documents for an agent"""
    try:
        success = await rag_service.delete_agent_documents(company_id, agent_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete documents")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error deleting documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@rag_router.post("/query/{company_id}")
async def query_documents(
    company_id: str,
    question: str,
    agent_id: Optional[str] = None,
    conversation_context: Optional[List[Dict]] = None
) -> StreamingResponse:
    """Query the RAG system with streaming response"""
    try:
        # Create QA chain for the company/agent
        chain = await rag_service.create_qa_chain(company_id, agent_id)
        
        # Create streaming response
        return StreamingResponse(
            rag_service.get_answer_with_chain(chain, question, conversation_context),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Error querying documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))