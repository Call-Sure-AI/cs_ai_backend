from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List, Dict, Any, Optional
from src.services.data.data_loaders import DocumentLoader, DatabaseLoader
import logging

logger = logging.getLogger(__name__)
data_router = APIRouter()
document_loader = DocumentLoader()
database_loader = DatabaseLoader()

@data_router.post("/load-documents")
async def load_documents(
    files: List[UploadFile] = File(...),
    process_text: bool = True
) -> List[Dict[str, Any]]:
    """Load and process uploaded documents"""
    try:
        results = []
        for file in files:
            # Save uploaded file temporarily
            temp_path = f"/tmp/{file.filename}"
            with open(temp_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
            
            # Process document
            doc = await document_loader.load_document(temp_path)
            if doc:
                results.append(doc)
                
            # Cleanup
            import os
            os.remove(temp_path)
            
        return results
    except Exception as e:
        logger.error(f"Error processing documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@data_router.post("/load-database")
async def load_database_data(
    connection_params: Dict[str, Any],
    tables_config: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Load and process database tables"""
    try:
        return await database_loader.load_database(
            connection_params,
            tables_config
        )
    except Exception as e:
        logger.error(f"Error loading database: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))