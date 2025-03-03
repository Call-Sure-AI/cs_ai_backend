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

# @router.post("/agents")
# async def create_agent_with_documents(
#     name: str = Form(...),
#     type: str = Form(...),
#     company_id: str = Form(...),
#     prompt: str = Form(...),
#     files: List[UploadFile] = File(None),
#     descriptions: Optional[str] = Form(None),
#     db: Session = Depends(get_db)
# ):
#     """
#     Create a new agent with support for multiple file uploads (documents and images)
#     """
#     try:
#         logger.info(f"Creating agent with name: {name}, type: {type}, company_id: {company_id}")
#         logger.info(f"Files received: {[f.filename for f in files] if files else None}")
        
#         # Create agent
#         agent = Agent(
#             id=str(uuid.uuid4()),
#             name=name,
#             type=type.lower(),
#             company_id=company_id,
#             prompt=prompt,
#             active=True
#         )
        
#         db.add(agent)
#         db.commit()
#         db.refresh(agent)

#         document_ids = []
#         image_ids = []

#         if files:
#             # Parse descriptions if provided
#             descriptions_dict = {}
#             if descriptions:
#                 try:
#                     descriptions_dict = json.loads(descriptions)
#                 except json.JSONDecodeError:
#                     logger.warning("Invalid descriptions JSON provided")

#             # Initialize services
#             qdrant_service = QdrantService()
#             document_embedding_service = DocumentEmbeddingService(qdrant_service)
#             image_embedding_service = ImageEmbeddingService(qdrant_service)
            
#             # Ensure collection exists
#             await qdrant_service.setup_collection(company_id)
            
#             # Separate files into images and documents
#             image_files = []
#             document_files = []
            
#             for file in files:
#                 try:
#                     content = await file.read()
                    
#                     # Determine if file is an image
#                     is_image = is_image_file(file.content_type)
                    
#                     # Create document record
#                     document = Document(
#                         company_id=company_id,
#                         agent_id=agent.id,
#                         name=file.filename,
#                         content=content,
#                         file_type=file.content_type,
#                         type=DocumentType.image if is_image else DocumentType.custom,
#                         metadata={
#                             "description": descriptions_dict.get(file.filename) if is_image else None,
#                             "original_filename": file.filename,
#                             "uploaded_at": datetime.now().isoformat()
#                         }
#                     )
                    
#                     db.add(document)
#                     db.commit()
#                     db.refresh(document)
                    
#                     # Add to appropriate list based on file type
#                     if is_image:
#                         image_files.append({
#                             'id': document.id,
#                             'content': content,
#                             'description': descriptions_dict.get(file.filename),
#                             'filename': file.filename,
#                             'content_type': file.content_type,
#                             'metadata': {
#                                 'agent_id': agent.id,
#                                 'original_filename': file.filename
#                             }
#                         })
#                         image_ids.append(document.id)
#                     else:
#                         document_files.append({
#                             'id': document.id,
#                             'content': content,
#                             'metadata': {
#                                 'agent_id': agent.id,
#                                 'filename': file.filename,
#                                 'file_type': file.content_type
#                             }
#                         })
#                         document_ids.append(document.id)
                            
#                 except Exception as e:
#                     logger.error(f"Error processing file {file.filename}: {str(e)}")
#                     continue
            
#             # Process documents and images in parallel if possible
#             embed_tasks = []
            
#             # Embed documents if any
#             if document_files:
#                 success = await document_embedding_service.embed_documents(
#                     company_id=company_id,
#                     agent_id=agent.id,
#                     documents=document_files
#                 )
#                 if not success:
#                     logger.error("Failed to embed documents")
            
#             # Embed images if any
#             if image_files:
#                 success = await image_embedding_service.embed_images(
#                     company_id=company_id,
#                     agent_id=agent.id,
#                     images=image_files
#                 )
#                 if not success:
#                     logger.error("Failed to embed images")

#         return {
#             "status": "success",
#             "agent": {
#                 "id": agent.id,
#                 "name": agent.name,
#                 "type": agent.type,
#                 "company_id": agent.company_id,
#                 "prompt": agent.prompt
#             },
#             "documents": {
#                 "total": len(document_ids) + len(image_ids),
#                 "document_ids": document_ids,
#                 "image_ids": image_ids
#             }
#         }

#     except Exception as e:
#         logger.error(f"Error creating agent: {str(e)}", exc_info=True)
#         db.rollback()
#         raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents")
async def create_agent_with_documents(
    name: str = Form(...),
    type: str = Form(...),
    company_id: str = Form(...),
    prompt: str = Form(...),
    file_urls: Optional[str] = Form(None),  # JSON string of file URLs
    descriptions: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Create a new agent with support for multiple file URLs (documents and images)
    """
    try:
        logger.info(f"Creating agent with name: {name}, type: {type}, company_id: {company_id}")
        
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

        if file_urls:
            # Parse file URLs
            try:
                urls_list = json.loads(file_urls)
                logger.info(f"File URLs received: {urls_list}")
            except json.JSONDecodeError:
                logger.error("Invalid file URLs JSON provided")
                raise HTTPException(status_code=400, detail="Invalid file URLs format")

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
            
            # Process each file URL
            image_files = []
            document_files = []
            
            for url in urls_list:
                try:
                    # List objects in bucket to verify exact key
                    filename = url.split('/')[-1]
                    logger.info(f"Original filename from URL: {filename}")
                    
                    # Try downloading directly using boto3
                    content, content_type = download_from_s3_direct(url)
                    
                    if not content:
                        logger.warning(f"Failed to download content for URL: {url}")
                        continue
                    
                    logger.info(f"Downloaded file: {filename}, size: {len(content)} bytes, content type: {content_type}")
                    
                    # Determine if file is an image
                    is_image = is_image_file(content_type)
                    
                    # Create document record
                    document = Document(
                        company_id=company_id,
                        agent_id=agent.id,
                        name=filename,
                        content=content,
                        file_type=content_type,
                        type=DocumentType.image if is_image else DocumentType.custom,
                        metadata={
                            "description": descriptions_dict.get(filename) if is_image else None,
                            "original_filename": filename,
                            "file_url": url,
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
                            'description': descriptions_dict.get(filename),
                            'filename': filename,
                            'content_type': content_type,
                            'metadata': {
                                'agent_id': agent.id,
                                'original_filename': filename,
                                'file_url': url
                            }
                        })
                        image_ids.append(document.id)
                    else:
                        document_files.append({
                            'id': document.id,
                            'content': content,
                            'metadata': {
                                'agent_id': agent.id,
                                'filename': filename,
                                'file_type': content_type,
                                'file_url': url
                            }
                        })
                        document_ids.append(document.id)
                            
                except Exception as e:
                    logger.error(f"Error processing URL {url}: {str(e)}")
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

def list_s3_bucket_objects(bucket_name, prefix=''):
    """
    List objects in an S3 bucket with an optional prefix
    """
    try:
        import boto3
        
        s3_client = boto3.client(
            's3',
            region_name='ap-south-1',
            aws_access_key_id='AKIAST6S66NLF5CSVGVB',
            aws_secret_access_key='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'
        )
        
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=100
        )
        
        if 'Contents' in response:
            objects = [obj['Key'] for obj in response['Contents']]
            logger.info(f"Found {len(objects)} objects in bucket {bucket_name} with prefix '{prefix}'")
            logger.info(f"Objects: {objects[:10]}")
            return objects
        else:
            logger.warning(f"No objects found in bucket {bucket_name} with prefix '{prefix}'")
            return []
    except Exception as e:
        logger.error(f"Error listing S3 bucket objects: {str(e)}")
        return []

def download_from_s3_direct(url):
    """
    Download an S3 object directly using boto3, with special handling for URL formats
    """
    try:
        import boto3
        import re
        from urllib.parse import urlparse, unquote
        
        logger.info(f"Attempting to download directly from URL: {url}")
        
        # Parse URL to get bucket and key
        parsed_url = urlparse(url)
        
        # Check for different S3 URL formats
        if parsed_url.netloc.endswith('.amazonaws.com'):
            # Format: https://bucket-name.s3.region.amazonaws.com/key
            if '.s3.' in parsed_url.netloc:
                parts = parsed_url.netloc.split('.s3.')
                bucket_name = parts[0]
                key = unquote(parsed_url.path.lstrip('/'))
            # Format: https://s3.region.amazonaws.com/bucket-name/key
            elif parsed_url.netloc.startswith('s3.'):
                path_parts = parsed_url.path.lstrip('/').split('/', 1)
                if len(path_parts) >= 2:
                    bucket_name = path_parts[0]
                    key = unquote(path_parts[1])
                else:
                    logger.error(f"Invalid S3 URL format (path): {url}")
                    return None, None
            else:
                logger.error(f"Unrecognized S3 URL format: {url}")
                return None, None
        else:
            logger.error(f"URL is not an S3 URL: {url}")
            return None, None
        
        logger.info(f"Parsed S3 URL: bucket={bucket_name}, key={key}")
        
        # Check if objects exist with similar names
        similar_objects = list_s3_bucket_objects(bucket_name, key.split('/')[-1].split('-')[0])
        
        if not similar_objects and '-' in key:
            # Try finding objects with different formatting of the key
            base_name = key.split('/')[-1].split('-')[0]
            similar_objects = list_s3_bucket_objects(bucket_name, base_name)
            
            if similar_objects:
                # Use the first similar object
                key = similar_objects[0]
                logger.info(f"Using similar object key: {key}")
        
        # Set up S3 client
        s3_client = boto3.client(
            's3',
            region_name='ap-south-1',
            aws_access_key_id='AKIAST6S66NLF5CSVGVB',
            aws_secret_access_key='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'
        )
        
        # Try to get the object
        try:
            logger.info(f"Getting object from S3: bucket={bucket_name}, key={key}")
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            content = response['Body'].read()
            content_type = response.get('ContentType', 'application/octet-stream')
            
            logger.info(f"Successfully downloaded S3 object: {key} ({len(content)} bytes)")
            return content, content_type
        except Exception as e:
            logger.error(f"Error getting S3 object: {str(e)}")
            
            # If object not found, try to list objects to see if we can find it
            if 'NoSuchKey' in str(e):
                # List objects in the bucket to see what's available
                all_objects = list_s3_bucket_objects(bucket_name, '')
                
                # Extract the filename and try to find a match
                target_filename = key.split('/')[-1]
                for obj_key in all_objects:
                    if target_filename in obj_key:
                        logger.info(f"Found potential match: {obj_key}")
                        try:
                            response = s3_client.get_object(Bucket=bucket_name, Key=obj_key)
                            content = response['Body'].read()
                            content_type = response.get('ContentType', 'application/octet-stream')
                            logger.info(f"Successfully downloaded alternative S3 object: {obj_key}")
                            return content, content_type
                        except Exception as inner_e:
                            logger.error(f"Error getting alternative S3 object: {str(inner_e)}")
            
            return None, None
    except Exception as e:
        logger.error(f"Error in download_from_s3_direct: {str(e)}")
        return None, None

def get_content_type_from_extension(extension: str) -> str:
    """
    Get MIME type from file extension
    """
    extension_to_mime = {
        'pdf': 'application/pdf',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        'csv': 'text/csv',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ppt': 'application/vnd.ms-powerpoint',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'svg': 'image/svg+xml',
        'html': 'text/html',
        'json': 'application/json'
    }
    
    return extension_to_mime.get(extension, 'application/octet-stream')


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