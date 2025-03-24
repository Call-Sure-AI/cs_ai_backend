import os
import uuid
import asyncio
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List, Dict, Any, Optional
from src.services.data.data_loaders import DocumentLoader, DatabaseLoader
import logging

logger = logging.getLogger(__name__)
data_router = APIRouter()
document_loader = DocumentLoader()
database_loader = DatabaseLoader()

# Configuration constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
TEMP_DIR = "/tmp"
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.csv', '.xlsx'}

def get_safe_filename(original_filename: str) -> str:
    """Generate a safe, unique filename while preserving the extension"""
    if not original_filename:
        return f"{uuid.uuid4()}.tmp"
    
    # Get the extension but verify it's safe
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4()}{ext}"

@data_router.post("/load-documents")
async def load_documents(
    files: List[UploadFile] = File(...),
    process_text: bool = True,
    max_size: int = MAX_FILE_SIZE
) -> List[Dict[str, Any]]:
    """Load and process uploaded documents"""
    temp_files = []
    results = []
    
    try:
        processing_tasks = []
        
        for file in files:
            # Check file size
            if file.size and file.size > max_size:
                logger.warning(f"File too large: {file.filename} ({file.size} bytes)")
                continue
                
            # Validate file extension
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                logger.warning(f"Unsupported file extension: {file_ext}")
                continue
            
            # Create safe filename and path
            safe_filename = get_safe_filename(file.filename)
            temp_path = os.path.join(TEMP_DIR, safe_filename)
            temp_files.append(temp_path)
            
            # Save uploaded file temporarily
            content = await file.read()
            with open(temp_path, "wb") as buffer:
                buffer.write(content)
            
            # Add to processing tasks
            processing_tasks.append(document_loader.load_document(temp_path))
        
        # Process documents concurrently
        if processing_tasks:
            processed_docs = await asyncio.gather(*processing_tasks, return_exceptions=True)
            
            for doc in processed_docs:
                if isinstance(doc, Exception):
                    logger.error(f"Error processing document: {str(doc)}")
                    continue
                if doc:
                    results.append(doc)
                    
        return results
    except Exception as e:
        logger.error(f"Error processing documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        for temp_path in temp_files:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception as e:
                logger.error(f"Error removing temp file {temp_path}: {str(e)}")

@data_router.post("/load-database")
async def load_database_data(
    connection_params: Dict[str, Any],
    tables_config: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Load and process database tables"""
    try:
        # Validate connection parameters for basic security
        if not connection_params or not isinstance(connection_params, dict):
            raise HTTPException(status_code=400, detail="Invalid connection parameters")
            
        # Validate tables configuration
        if not tables_config or not isinstance(tables_config, list):
            raise HTTPException(status_code=400, detail="Invalid tables configuration")
            
        return await database_loader.load_database(
            connection_params,
            tables_config
        )
    except Exception as e:
        logger.error(f"Error loading database: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

"""

I can spot several issues in this code:
- Potential path traversal vulnerability: Using file.filename directly in the file path without sanitization allows an attacker to potentially access or overwrite files outside the intended directory.
- Improper resource management: If an exception occurs during file processing, the temporary file might not be deleted.
- Unnecessary import inside function: The os module is imported inside the function, which is inefficient and not following best practices.
- No file size limiting: There's no check for file size limits, which could lead to denial of service attacks via large file uploads.
- Import path issue: Using src.services.data.data_loaders suggests this file might be outside the main module structure, which could cause import issues depending on how the application is run.
- No content type validation: The code doesn't verify file types before processing them.
- No concurrent request handling: Processing files sequentially could be inefficient for multiple large files.
- Temporary file naming collision: Using just the filename could cause collisions if multiple users upload files with the same name.


Changes made by Sai
- Uses a safer method to generate temporary filenames
- Validates file types and sizes
- Handles resources properly with try/finally
- Uses concurrent processing
- Performs input validation
- Follows proper import practices
- Has better error handling
"""