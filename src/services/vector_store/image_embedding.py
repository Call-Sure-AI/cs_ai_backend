from typing import List, Dict, Optional, Any, Tuple
import logging
from datetime import datetime
import base64
from PIL import Image
import io
import uuid
import httpx
import asyncio
from qdrant_client import models
from langchain_openai import OpenAIEmbeddings
from config.settings import settings

logger = logging.getLogger(__name__)

class ImageEmbeddingService:
    def __init__(self, qdrant_service):
        """Initialize Image Embedding Service"""
        self.qdrant_service = qdrant_service
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=settings.OPENAI_API_KEY
        )
        
        self.openai_api_key = settings.OPENAI_API_KEY
        # Cache for image descriptions to avoid redundant API calls
        self._description_cache = {}
        # Semaphore to control concurrent Vision API requests
        self._vision_api_semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests
    
    async def get_image_description(self, image_content: bytes, 
                                  retry_count: int = 3) -> Tuple[str, bool]:
        """
        Get image description using OpenAI's Vision API
        
        Returns:
            Tuple[str, bool]: (description, success_flag)
        """
        # Generate a hash of the image to use as cache key
        image_hash = hash(image_content)
        if image_hash in self._description_cache:
            return self._description_cache[image_hash], True
        
        async with self._vision_api_semaphore:
            for attempt in range(retry_count):
                try:
                    # Convert image to base64
                    base64_image = base64.b64encode(image_content).decode('utf-8')
                    
                    # Prepare the API request
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.openai_api_key}"
                    }
                    
                    payload = {
                        "model": "gpt-4o-mini",  # Using the current model name for vision
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Please provide a detailed description of this image, including key elements, colors, composition, and any text or notable features."
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_image}",
                                            "detail": "high"  # Request high detail analysis
                                        }
                                    }
                                ]
                            }
                        ],
                        "max_tokens": 300
                    }
                    
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        response = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers=headers,
                            json=payload
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            description = result['choices'][0]['message']['content']
                            logger.info(f"Generated description: {description[:100]}...")
                            # Cache the successful result
                            self._description_cache[image_hash] = description
                            return description, True
                        elif response.status_code == 429:  # Rate limit error
                            wait_time = min(2 ** attempt, 60)  # Exponential backoff capped at 60s
                            logger.warning(f"Rate limit hit, waiting {wait_time}s before retry")
                            await asyncio.sleep(wait_time)
                        else:
                            error_message = f"Error from OpenAI API: {response.status_code} - {response.text}"
                            logger.error(error_message)
                            
                            if attempt < retry_count - 1:
                                wait_time = 2 ** attempt
                                logger.info(f"Retrying in {wait_time} seconds...")
                                await asyncio.sleep(wait_time)
                            else:
                                break
                            
                except Exception as e:
                    error_message = f"Error getting image description (attempt {attempt+1}/{retry_count}): {str(e)}"
                    logger.error(error_message)
                    
                    if attempt < retry_count - 1:
                        wait_time = 2 ** attempt
                        logger.info(f"Retrying in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                    else:
                        break
            
            # Fallback description if all retries fail
            fallback = """Error generating image description. Using fallback description:
            This is an uploaded image. For detailed information about its contents, 
            please refer to any user-provided description."""
            return fallback, False
    
    def _get_image_info(self, image_content: bytes) -> Dict[str, Any]:
        """Extract basic information from image data"""
        try:
            image = Image.open(io.BytesIO(image_content))
            
            return {
                "size": image.size,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "format": image.format,
                "has_exif": hasattr(image, "_getexif") and bool(image._getexif())
            }
        except Exception as e:
            logger.error(f"Error extracting image info: {str(e)}")
            return {
                "size": None,
                "width": None,
                "height": None,
                "mode": None,
                "format": None,
                "has_exif": False,
                "error": str(e)
            }
    
    async def process_image(
        self,
        image_content: bytes,
        user_description: Optional[str] = None,
        image_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process image and generate embeddings with descriptions"""
        try:
            # Get image details
            image_info = self._get_image_info(image_content)
            
            # Get OpenAI description
            auto_description, success = await self.get_image_description(image_content)
            
            # Combine descriptions
            combined_description = f"""
            User Description: {user_description if user_description else 'Not provided'}
            
            AI Description: {auto_description}
            
            Image Details:
            - Size: {image_info.get('width')}x{image_info.get('height')}
            - Format: {image_info.get('format')}
            - ID: {image_id or 'Not provided'}
            """
            
            # Generate embedding
            embedding = await self.embed_with_retries(combined_description)
            
            return {
                "description": combined_description,
                "auto_description": auto_description,
                "embedding": embedding,
                "metadata": {
                    "has_user_description": bool(user_description),
                    "image_info": image_info,
                    "description_success": success,
                    "processed_at": datetime.utcnow().isoformat(),
                    "image_id": image_id
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise
    
    async def embed_with_retries(self, text: str, max_retries: int = 3) -> List[float]:
        """Generate embedding with retry logic"""
        for attempt in range(max_retries):
            try:
                return await self.embeddings.aembed_query(text)
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Embedding attempt {attempt+1} failed, retrying in {wait_time}s: {str(e)}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"All embedding attempts failed: {str(e)}")
                    raise
    
    async def embed_images(
        self,
        company_id: str,
        agent_id: str,
        images: List[Dict[str, Any]],
        batch_size: int = 3
    ) -> bool:
        """Process and embed images into the vector database"""
        try:
            logger.info(f"Embedding {len(images)} images for agent {agent_id}")
            
            # Process images in batches
            total_successful = 0
            total_failed = 0
            
            # Group images into batches
            for i in range(0, len(images), batch_size):
                batch = images[i:i+batch_size]
                batch_tasks = []
                
                for image_data in batch:
                    # Create task for processing each image
                    task = self.process_image(
                        image_content=image_data['content'],
                        user_description=image_data.get('description'),
                        image_id=image_data.get('id')
                    )
                    batch_tasks.append((image_data, task))
                
                # Process batch concurrently
                points = []
                for image_data, task in batch_tasks:
                    try:
                        processed = await task
                        
                        # Create point
                        points.append(models.PointStruct(
                            id=str(uuid.uuid4()),
                            vector=processed['embedding'],
                            payload={
                                'page_content': processed['description'],
                                'auto_description': processed['auto_description'],
                                'metadata': {
                                    **processed['metadata'],
                                    'agent_id': agent_id,
                                    'document_id': image_data['id'],
                                    'original_filename': image_data.get('filename'),
                                    'content_type': image_data.get('content_type'),
                                    'type': 'image'
                                }
                            }
                        ))
                        
                        total_successful += 1
                        
                    except Exception as e:
                        logger.error(f"Error processing image {image_data.get('id')}: {str(e)}")
                        total_failed += 1
                        continue
                
                # Add batch of points to Qdrant
                if points:
                    batch_result = await self.qdrant_service.add_points(company_id, points)
                    if not batch_result:
                        logger.error(f"Failed to add batch of {len(points)} images to vector store")
                
                logger.info(f"Processed batch {i//batch_size + 1}/{(len(images) + batch_size - 1)//batch_size}: "
                           f"{len(points)} successful, {batch_size - len(points)} failed")
            
            logger.info(f"Image embedding complete: {total_successful} successful, {total_failed} failed")
            
            # Return success if at least one image was processed
            return total_successful > 0
            
        except Exception as e:
            logger.error(f"Error embedding images: {str(e)}")
            return False
    
    async def replace_image_embedding(
        self,
        company_id: str,
        agent_id: str,
        image_id: str,
        new_image_content: bytes,
        user_description: Optional[str] = None
    ) -> bool:
        """Replace embedding for an existing image"""
        try:
            # Delete existing vectors for this image
            filter_condition = {
                "metadata.document_id": image_id
            }
            
            # Delete existing points
            deletion_result = await self.qdrant_service.delete_points(
                company_id, 
                filter_condition
            )
            
            if not deletion_result:
                logger.warning(f"No existing embeddings found for image {image_id}")
            
            # Process the new image
            processed = await self.process_image(
                image_content=new_image_content,
                user_description=user_description,
                image_id=image_id
            )
            
            # Create and add new point
            point = models.PointStruct(
                id=str(uuid.uuid4()),
                vector=processed['embedding'],
                payload={
                    'page_content': processed['description'],
                    'auto_description': processed['auto_description'],
                    'metadata': {
                        **processed['metadata'],
                        'agent_id': agent_id,
                        'document_id': image_id,
                        'type': 'image',
                        'updated_at': datetime.utcnow().isoformat()
                    }
                }
            )
            
            result = await self.qdrant_service.add_points(company_id, [point])
            logger.info(f"Updated embedding for image {image_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error replacing image embedding: {str(e)}")
            return False
    
    async def search_similar_images(
        self,
        company_id: str,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar images based on text query"""
        try:
            # Generate embedding for the query
            query_embedding = await self.embed_with_retries(query)
            
            # Prepare filter
            filter_condition = {
                "payload.metadata.type": "image"
            }
            
            if agent_id:
                filter_condition["payload.metadata.agent_id"] = agent_id
                
            # Search in vector DB
            results = await self.qdrant_service.search(
                company_id,
                query_embedding,
                filter_condition=filter_condition,
                limit=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching similar images: {str(e)}")
            return []

"""
Key Improvements:
- Improved Error Handling: Added robust error handling with retry logic for both API calls and embeddings.
- Rate Limit Handling: Added exponential backoff for rate limit errors from the OpenAI API.
- Description Caching: Added a cache for image descriptions to avoid redundant API calls for identical images.
- Concurrent Processing Control: Added a semaphore to limit concurrent Vision API requests.
- Better Image Analysis: Separated image analysis into its own method for better error isolation.
- Batched Processing: Implemented batch processing for images to improve efficiency and control concurrency.
- Embedding Retry Logic: Added embed_with_retries method to handle API failures gracefully.
- Image Replacement Function: Added ability to replace embeddings for existing images.
- Similar Image Search: Added method to search for similar images based on text queries.
- Success/Failure Tracking: Added tracking of successful and failed image processing.
- Improved Timeout Handling: Increased the timeout for HTTPX client to handle larger images.
- Better Metadata: Enhanced the metadata stored with embeddings for more detailed searching.

These improvements address potential reliability issues, improve efficiency, and add useful functionality to the ImageEmbeddingService class. The updated code should be more robust when dealing with API rate limits, network issues, and large volumes of images.
"""