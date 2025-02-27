# api/routes/admin_routes.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from pydantic import BaseModel
import json
from datetime import datetime
import uuid

from database.config import get_db
from database.models import Company, Agent, Document, DatabaseIntegration, DocumentType
from services.vector_store.qdrant_service import QdrantService
from services.rag.rag_service import RAGService
from services.vector_store.document_embedding import DocumentEmbeddingService
from services.vector_store.image_embedding import ImageEmbeddingService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/companies")
async def create_company(
    company_data: dict,
    db: Session = Depends(get_db)
):
    try:
        # Generate a unique API key if not provided
        if 'api_key' not in company_data or not company_data['api_key']:
            company_data['api_key'] = str(uuid.uuid4())
        logger.info(f"Generated API key: {company_data['api_key']}")
        
        company = Company(**company_data)
        db.add(company)
        db.commit()
        db.refresh(company)
        return company
    except Exception as e:
        logger.error(f"Error creating company: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating company: {str(e)}")

@router.post("/companies/login")
async def login_company(
    login_data: dict,
    db: Session = Depends(get_db)
):
    try:
        # Validate email and API key
        company = db.query(Company).filter(
            Company.email == login_data.get("email"),
            Company.api_key == login_data.get("api_key")
        ).first()
        
        if not company:
            raise HTTPException(status_code=401, detail="Invalid email or API key")
        
        # Return company details upon successful login
        return {
            "id": company.id,
            "name": company.name,
            "email": company.email,
            "api_key": company.api_key,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")

def is_image_file(content_type: str) -> bool:
    """Check if the file is an image based on content type"""
    return content_type.startswith('image/')

@router.post("/agents")
async def create_agent_with_documents(
    name: str = Form(...),
    type: str = Form(...),
    company_id: str = Form(...),
    prompt: str = Form(...),
    files: List[UploadFile] = File(None),
    descriptions: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Create a new agent with support for multiple file uploads (documents and images)
    """
    try:
        logger.info(f"Creating agent with name: {name}, type: {type}, company_id: {company_id}")
        logger.info(f"Files received: {[f.filename for f in files] if files else None}")
        
        # Create agent
        agent = Agent(
            id=str(uuid.uuid4()),
            name=name,
            type=type.lower(),
            company_id=company_id,
            prompt=prompt,
            active=True
        )
        
        db.add(agent)
        db.commit()
        db.refresh(agent)

        document_ids = []
        image_ids = []

        if files:
            # Parse descriptions if provided
            descriptions_dict = {}
            if descriptions:
                try:
                    descriptions_dict = json.loads(descriptions)
                except json.JSONDecodeError:
                    logger.warning("Invalid descriptions JSON provided")

            # Initialize services
            qdrant_service = QdrantService()
            document_embedding_service = DocumentEmbeddingService(qdrant_service)
            image_embedding_service = ImageEmbeddingService(qdrant_service)
            
            # Ensure collection exists
            await qdrant_service.setup_collection(company_id)
            
            # Separate files into images and documents
            image_files = []
            document_files = []
            
            for file in files:
                try:
                    content = await file.read()
                    
                    # Determine if file is an image
                    is_image = is_image_file(file.content_type)
                    
                    # Create document record
                    document = Document(
                        company_id=company_id,
                        agent_id=agent.id,
                        name=file.filename,
                        content=content,
                        file_type=file.content_type,
                        type=DocumentType.image if is_image else DocumentType.custom,
                        metadata={
                            "description": descriptions_dict.get(file.filename) if is_image else None,
                            "original_filename": file.filename,
                            "uploaded_at": datetime.now().isoformat()
                        }
                    )
                    
                    db.add(document)
                    db.commit()
                    db.refresh(document)
                    
                    # Add to appropriate list based on file type
                    if is_image:
                        image_files.append({
                            'id': document.id,
                            'content': content,
                            'description': descriptions_dict.get(file.filename),
                            'filename': file.filename,
                            'content_type': file.content_type,
                            'metadata': {
                                'agent_id': agent.id,
                                'original_filename': file.filename
                            }
                        })
                        image_ids.append(document.id)
                    else:
                        document_files.append({
                            'id': document.id,
                            'content': content,
                            'metadata': {
                                'agent_id': agent.id,
                                'filename': file.filename,
                                'file_type': file.content_type
                            }
                        })
                        document_ids.append(document.id)
                            
                except Exception as e:
                    logger.error(f"Error processing file {file.filename}: {str(e)}")
                    continue
            
            # Process documents and images in parallel if possible
            embed_tasks = []
            
            # Embed documents if any
            if document_files:
                success = await document_embedding_service.embed_documents(
                    company_id=company_id,
                    agent_id=agent.id,
                    documents=document_files
                )
                if not success:
                    logger.error("Failed to embed documents")
            
            # Embed images if any
            if image_files:
                success = await image_embedding_service.embed_images(
                    company_id=company_id,
                    agent_id=agent.id,
                    images=image_files
                )
                if not success:
                    logger.error("Failed to embed images")

        return {
            "status": "success",
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type,
                "company_id": agent.company_id,
                "prompt": agent.prompt
            },
            "documents": {
                "total": len(document_ids) + len(image_ids),
                "document_ids": document_ids,
                "image_ids": image_ids
            }
        }

    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/documents/upload")
async def upload_documents(
    company_id: str,
    agent_id: str,
    files: List[UploadFile] = File(...),
    descriptions: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload and process documents and images for an existing agent
    """
    try:
        # Check if agent exists
        agent = db.query(Agent).filter_by(id=agent_id, company_id=company_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        # Parse descriptions if provided
        descriptions_dict = {}
        if descriptions:
            try:
                descriptions_dict = json.loads(descriptions)
            except json.JSONDecodeError:
                logger.warning("Invalid descriptions JSON provided")
        
        # Initialize services
        qdrant_service = QdrantService()
        document_embedding_service = DocumentEmbeddingService(qdrant_service)
        image_embedding_service = ImageEmbeddingService(qdrant_service)
        
        # Ensure collection exists
        await qdrant_service.setup_collection(company_id)
        
        # Process files
        document_ids = []
        image_ids = []
        document_files = []
        image_files = []
        
        for file in files:
            try:
                content = await file.read()
                
                # Determine if file is an image
                is_image = is_image_file(file.content_type)
                
                # Create document record
                document = Document(
                    company_id=company_id,
                    agent_id=agent_id,
                    name=file.filename,
                    content=content,
                    file_type=file.content_type,
                    type=DocumentType.image if is_image else DocumentType.custom,
                    metadata={
                        "description": descriptions_dict.get(file.filename) if is_image else None,
                        "original_filename": file.filename,
                        "uploaded_at": datetime.now().isoformat()
                    }
                )
                
                db.add(document)
                db.commit()
                db.refresh(document)
                
                # Add to appropriate list based on file type
                if is_image:
                    image_files.append({
                        'id': document.id,
                        'content': content,
                        'description': descriptions_dict.get(file.filename),
                        'filename': file.filename,
                        'content_type': file.content_type,
                        'metadata': {
                            'agent_id': agent_id,
                            'original_filename': file.filename
                        }
                    })
                    image_ids.append(document.id)
                else:
                    document_files.append({
                        'id': document.id,
                        'content': content,
                        'metadata': {
                            'agent_id': agent_id,
                            'filename': file.filename,
                            'file_type': file.content_type
                        }
                    })
                    document_ids.append(document.id)
                        
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {str(e)}")
                continue
        
        # Process documents if any
        if document_files:
            success = await document_embedding_service.embed_documents(
                company_id=company_id,
                agent_id=agent_id,
                documents=document_files
            )
            if not success:
                logger.error("Failed to embed documents")
        
        # Process images if any
        if image_files:
            success = await image_embedding_service.embed_images(
                company_id=company_id,
                agent_id=agent_id,
                images=image_files
            )
            if not success:
                logger.error("Failed to embed images")
        
        return {
            "status": "success",
            "message": f"Successfully uploaded {len(document_ids) + len(image_ids)} files",
            "documents": {
                "total": len(document_ids) + len(image_ids),
                "document_ids": document_ids,
                "image_ids": image_ids
            }
        }
        
    except Exception as e:
        logger.error(f"Error uploading documents: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/{company_id}")
async def get_company_agents(company_id: str, db: Session = Depends(get_db)):
    try:
        agents = db.query(Agent).filter_by(company_id=company_id, active=True).all()
        return [{
            "id": agent.id,
            "name": agent.name,
            "type": agent.type,
            "prompt": agent.prompt,
            "documents": len(agent.documents)
        } for agent in agents]
    except Exception as e:
        logger.error(f"Error getting agents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))