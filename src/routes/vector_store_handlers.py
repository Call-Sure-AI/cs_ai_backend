from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional, Any
from src.services.vector_store.qdrant_service import QdrantService
from src.services.vector_store.chroma_service import VectorStore
import logging

logger = logging.getLogger(__name__)
vector_store_router = APIRouter()
qdrant_service = QdrantService()
vector_store = VectorStore()

@vector_store_router.post("/documents/{company_id}")
async def upload_documents(
    company_id: str,
    agent_id: str,
    documents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Upload documents with embeddings to vector store"""
    try:
        success = await qdrant_service.load_documents(
            company_id,
            agent_id,
            documents
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to upload documents")
        
        return {"status": "success", "documents_count": len(documents)}
    except Exception as e:
        logger.error(f"Error uploading documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@vector_store_router.post("/search/{company_id}")
async def search_documents(
    company_id: str,
    query_embedding: List[float],
    agent_id: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search documents using vector similarity"""
    try:
        results = await qdrant_service.search(
            company_id,
            query_embedding,
            agent_id,
            limit,
            settings.SEARCH_SCORE_THRESHOLD
        )
        return results
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@vector_store_router.post("/agents/{company_id}")
async def add_agents(
    company_id: str,
    agents: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Add multiple agents to the vector store"""
    try:
        success = await vector_store.batch_add_agents(company_id, agents)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add agents")
        return {"status": "success", "agents_count": len(agents)}
    except Exception as e:
        logger.error(f"Error adding agents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@vector_store_router.post("/agents/{company_id}/{agent_id}")
async def add_agent(
    company_id: str,
    agent_id: str,
    prompt: str,
    agent_type: str,
    confidence_threshold: float = None,
    metadata: Optional[Dict] = None
) -> Dict[str, str]:
    """Add a single agent to the vector store"""
    try:
        success = await vector_store.add_agent_prompt(
            company_id,
            agent_id,
            prompt,
            agent_type,
            confidence_threshold,
            metadata
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add agent")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error adding agent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@vector_store_router.get("/agents/{company_id}/{agent_id}")
async def get_agent(
    company_id: str,
    agent_id: str
) -> Dict[str, Any]:
    """Get agent information"""
    try:
        agent_info = await vector_store.get_agent_info(company_id, agent_id)
        if not agent_info:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent_info
    except Exception as e:
        logger.error(f"Error getting agent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@vector_store_router.post("/search/{company_id}")
async def find_agent(
    company_id: str,
    query: str,
    current_agent_id: Optional[str] = None,
    conversation_context: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """Find the most relevant agent for a query"""
    try:
        agent_id, confidence = await vector_store.find_relevant_agent(
            company_id,
            query,
            current_agent_id,
            conversation_context
        )
        return {
            "agent_id": agent_id,
            "confidence": confidence
        }
    except Exception as e:
        logger.error(f"Error finding agent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))