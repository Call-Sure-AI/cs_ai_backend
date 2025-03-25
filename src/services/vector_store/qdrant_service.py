from typing import Dict, List, Optional, Any, Union
import logging
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from config.settings import settings
import asyncio
from datetime import datetime
import time
import os
import json

logger = logging.getLogger(__name__)

class QdrantService:
    def __init__(self):
        """Initialize Qdrant service with necessary components"""
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=settings.OPENAI_API_KEY,
            client=None
        )
        
        self.qdrant_client = self._create_client()
        
        # Cache for vector stores with expiration
        self.vector_stores = {}
        self.vector_store_timestamps = {}
        self.cache_ttl = 3600  # 1 hour in seconds
        
        # Connection management
        self._client_lock = asyncio.Lock()
        self._connection_healthy = True
        self._last_health_check = time.time()
        self._health_check_interval = 300  # 5 minutes
        
        # Query embedding cache
        self._embedding_cache = {}
        self._embedding_cache_size = 100
    
    def _create_client(self) -> QdrantClient:
        """Create a new Qdrant client with retry capability"""
        try:
            return QdrantClient(
                url=f"https://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}",
                api_key=settings.QDRANT_API_KEY,
                timeout=30,  # Timeout for better reliability
                prefer_grpc=False  # Use HTTP for better error handling
            )
        except Exception as e:
            logger.error(f"Error creating Qdrant client: {str(e)}")
            raise
    
    async def _ensure_client_healthy(self):
        """Check client health and reconnect if needed"""
        async with self._client_lock:
            current_time = time.time()
            
            # Only check health periodically
            if (current_time - self._last_health_check < self._health_check_interval 
                and self._connection_healthy):
                return
            
            try:
                # Simple health check
                collections = self.qdrant_client.get_collections()
                self._connection_healthy = True
            except Exception as e:
                logger.error(f"Qdrant client unhealthy: {str(e)}")
                self._connection_healthy = False
                
                # Attempt reconnection
                try:
                    logger.info("Attempting to reconnect to Qdrant")
                    self.qdrant_client = self._create_client()
                    # Verify connection
                    collections = self.qdrant_client.get_collections()
                    self._connection_healthy = True
                    logger.info("Successfully reconnected to Qdrant")
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect to Qdrant: {str(reconnect_error)}")
                    raise
            
            self._last_health_check = current_time
    
    async def get_query_embedding(self, query: str) -> List[float]:
        """Get embedding for a query with caching"""
        # Check if query is in cache
        if query in self._embedding_cache:
            return self._embedding_cache[query]
        
        # Generate new embedding
        try:
            embedding = await self.embeddings.aembed_query(query)
            
            # Add to cache (with simple LRU behavior)
            if len(self._embedding_cache) >= self._embedding_cache_size:
                # Remove oldest item
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]
            
            self._embedding_cache[query] = embedding
            return embedding
        except Exception as e:
            logger.error(f"Error generating query embedding: {str(e)}")
            raise
    
    async def setup_collection(self, company_id: str) -> bool:
        """Setup or verify company collection exists"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Check if collection exists
            collections = self.qdrant_client.get_collections()
            collection_exists = any(col.name == collection_name for col in collections.collections)
            
            if not collection_exists:
                # Create collection if it doesn't exist
                self.qdrant_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=1536,  # For text-embedding-3-small
                        distance=models.Distance.COSINE
                    )
                )
                
                # Create indexes for faster filtering
                self.qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name="metadata.agent_id",
                    field_schema="keyword"
                )
                
                self.qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name="metadata.type",
                    field_schema="keyword"
                )
                
                self.qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name="metadata.doc_id",
                    field_schema="keyword"
                )
                
                logger.info(f"Created collection and indexes: {collection_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting up collection: {str(e)}")
            return False
    
    async def get_vector_store(self, company_id: str) -> QdrantVectorStore:
        """Get or create a vector store for a company with TTL-based caching"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Return cached vector store if available and not expired
            current_time = time.time()
            if (collection_name in self.vector_stores and 
                current_time - self.vector_store_timestamps.get(collection_name, 0) < self.cache_ttl):
                return self.vector_stores[collection_name]
            
            # Ensure collection exists
            await self.setup_collection(company_id)
            
            # Create vector store
            vector_store = QdrantVectorStore.from_existing_collection(
                embedding=self.embeddings,
                collection_name=collection_name,
                url=f"https://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}",
                api_key=settings.QDRANT_API_KEY,
                content_payload_key="page_content",
                metadata_payload_key="metadata"
            )
            # Cache the vector store with timestamp
            self.vector_stores[collection_name] = vector_store
            self.vector_store_timestamps[collection_name] = current_time
            
            return vector_store
            
        except Exception as e:
            logger.error(f"Error getting vector store: {str(e)}")
            raise
    
    async def add_points(
        self, 
        company_id: str, 
        points: List[models.PointStruct],
        max_retries: int = 3
    ) -> bool:
        """Add points to Qdrant collection with intelligent batch sizing and retries"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Ensure collection exists
            await self.setup_collection(company_id)
            
            # Start with a moderate batch size and adjust dynamically
            batch_size = 10  # Initial batch size
            min_batch_size = 1
            success_count = 0
            
            # Add points in dynamically sized batches
            for i in range(0, len(points), batch_size):
                batch = points[i:i + batch_size]
                retry_count = 0
                success = False
                
                while not success and retry_count < max_retries:
                    try:
                        self.qdrant_client.upsert(
                            collection_name=collection_name,
                            points=batch,
                            wait=True
                        )
                        # If successful, possibly increase batch size for efficiency
                        if batch_size < 50 and retry_count == 0:  # Only increase if succeeded on first try
                            batch_size = min(batch_size + 5, 50)
                        
                        success = True
                        success_count += len(batch)
                        logger.info(f"Added batch {i//batch_size + 1}/{(len(points)-1)//batch_size + 1} "
                                   f"({len(batch)} points, batch_size={batch_size})")
                    except Exception as batch_e:
                        retry_count += 1
                        logger.warning(f"Error adding batch (attempt {retry_count}/{max_retries}): {str(batch_e)}")
                        
                        # Reduce batch size on failure
                        old_batch_size = batch_size
                        batch_size = max(batch_size // 2, min_batch_size)
                        
                        if batch_size < old_batch_size and len(batch) > batch_size:
                            # Need to split the current batch
                            logger.info(f"Reducing batch size from {old_batch_size} to {batch_size} and retrying")
                            
                            # Only proceed with the smaller batch size for the next iteration
                            i = i - len(batch) + batch_size
                            batch = batch[:batch_size]
                        else:
                            # Wait before retry with exponential backoff
                            wait_time = 2 ** retry_count
                            logger.info(f"Waiting {wait_time}s before retry")
                            await asyncio.sleep(wait_time)
                
                # If still failed after all retries with smallest batch, process one by one
                if not success and batch_size > 1:
                    logger.warning(f"Batch insert failed, falling back to individual inserts")
                    for point in batch:
                        try:
                            self.qdrant_client.upsert(
                                collection_name=collection_name,
                                points=[point],
                                wait=True
                            )
                            success_count += 1
                            logger.info(f"Added single point after batch failure")
                        except Exception as point_e:
                            logger.error(f"Failed to add point: {str(point_e)}")
            
            logger.info(f"Added {success_count}/{len(points)} points to {collection_name}")
            # Return true only if all points were added
            return success_count == len(points)
            
        except Exception as e:
            logger.error(f"Error adding points: {str(e)}")
            return False
    
    async def delete_points(
        self, 
        company_id: str, 
        filter_condition: Dict[str, Any]
    ) -> bool:
        """Delete points matching a filter condition"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Build filter
            filter_obj = self._build_filter(filter_condition)
            
            # Delete points by filter
            deleted = self.qdrant_client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=filter_obj)
            )
            
            # Clear cache
            if collection_name in self.vector_stores:
                del self.vector_stores[collection_name]
                del self.vector_store_timestamps[collection_name]
            
            logger.info(f"Deleted points for filter {filter_condition} in collection {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting points: {str(e)}")
            return False
    
    def _build_filter(self, filter_dict: Dict[str, Any]) -> models.Filter:
        """Build a Qdrant filter from a dictionary"""
        must_conditions = []
        
        for key, value in filter_dict.items():
            # Handle nested keys like "metadata.doc_id"
            if value is not None:
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value)
                    )
                )
        
        return models.Filter(must=must_conditions) if must_conditions else None
    
    async def delete_agent_data(self, company_id: str, agent_id: str) -> bool:
        """Delete all data associated with an agent"""
        try:
            return await self.delete_points(
                company_id, 
                {"metadata.agent_id": agent_id}
            )
            
        except Exception as e:
            logger.error(f"Error deleting agent data: {str(e)}")
            return False
    
    async def search_by_filter(
        self,
        company_id: str,
        filter_condition: Dict[str, Any],
        limit: int = 100
    ) -> List[Dict]:
        """Search for points by filter without similarity"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Build filter
            filter_obj = self._build_filter(filter_condition)
            
            # Get points by scrolling
            all_points = []
            offset = None
            page_size = min(limit, 100)
            
            while len(all_points) < limit:
                points_batch, offset = self.qdrant_client.scroll(
                    collection_name=collection_name,
                    filter=filter_obj,
                    limit=page_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False  # Don't need vectors for filtering
                )
                
                if not points_batch:
                    break
                
                all_points.extend([
                    {
                        "id": point.id,
                        "payload": point.payload
                    }
                    for point in points_batch
                ])
                
                if offset is None:
                    break
            
            return all_points[:limit]
            
        except Exception as e:
            logger.error(f"Error searching by filter: {str(e)}")
            return []
    
    async def search(
        self,
        company_id: str,
        query_embedding: List[float],
        current_agent_id: Optional[str] = None,
        filter_condition: Optional[Dict[str, Any]] = None,
        limit: int = 5,
        score_threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors with optional filtering"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Build filter
            search_filter = None
            if filter_condition:
                search_filter = self._build_filter(filter_condition)
            elif current_agent_id:
                # Default filter by agent_id if specific filter not provided
                search_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.agent_id",
                            match=models.MatchValue(value=current_agent_id)
                        )
                    ]
                )
            
            # Execute search
            search_results = self.qdrant_client.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold
            )
            
            # Format results
            results = []
            for point in search_results:
                result = {
                    "id": point.id,
                    "score": point.score,
                    "page_content": point.payload.get("page_content", ""),
                    "metadata": point.payload.get("metadata", {})
                }
                # Add agent_id to result for easier access
                if "metadata" in point.payload and "agent_id" in point.payload["metadata"]:
                    result["agent_id"] = point.payload["metadata"]["agent_id"]
                    
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching: {str(e)}")
            return []
    
    async def get_existing_embeddings(
        self, 
        company_id: str, 
        agent_id: Optional[str] = None,
        limit: int = 500
    ) -> List[Dict]:
        """Get existing embeddings for a company/agent with pagination"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Prepare filter condition
            filter_condition = {}
            if agent_id:
                filter_condition["metadata.agent_id"] = agent_id
                
            return await self.search_by_filter(company_id, filter_condition, limit)
            
        except Exception as e:
            logger.error(f"Error getting existing embeddings: {str(e)}")
            return []
    
    async def verify_embeddings(self, company_id: str, agent_id: Optional[str] = None) -> bool:
        """Verify that embeddings exist and are accessible"""
        try:
            logger.info(f"Verifying embeddings for company {company_id}, agent {agent_id}")
            
            # Try to get some embeddings
            embeddings = await self.get_existing_embeddings(company_id, agent_id, limit=5)
            
            if not embeddings:
                logger.warning(f"No embeddings found for company {company_id} and agent {agent_id}")
                return False
            
            logger.info(f"Found {len(embeddings)} embeddings")
            
            # Verify the structure of the first embedding
            if embeddings and embeddings[0].get('payload') is not None:
                return True
            else:
                logger.error("Invalid embedding format found")
                return False
            
        except Exception as e:
            logger.error(f"Error verifying embeddings: {str(e)}")
            return False
    
    async def load_documents(
        self,
        company_id: str,
        agent_id: str,
        documents: List[Dict[str, Any]]
    ) -> bool:
        """Load documents into the vector store"""
        try:
            from src.services.vector_store.document_embedding import DocumentEmbeddingService
            
            # Create embedding service
            embedding_service = DocumentEmbeddingService(self)
            
            # Embed documents
            success = await embedding_service.embed_documents(
                company_id=company_id,
                agent_id=agent_id,
                documents=documents
            )
            
            return success
        except ImportError as e:
            logger.error(f"Error importing DocumentEmbeddingService: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error loading documents: {str(e)}")
            return False
    
    async def backup_embeddings(
        self,
        company_id: str,
        backup_dir: str = "embeddings_backup"
    ) -> str:
        """Backup all embeddings for a company to a local file"""
        try:
            await self._ensure_client_healthy()
            collection_name = f"company_{company_id}"
            
            # Create backup directory if it doesn't exist
            os.makedirs(backup_dir, exist_ok=True)
            
            # Timestamp for file name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"{collection_name}_{timestamp}.json")
            
            # Get all points with pagination
            all_points = []
            offset = None
            
            while True:
                points_batch, next_offset = self.qdrant_client.scroll(
                    collection_name=collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True
                )
                
                if not points_batch:
                    break
                
                # Convert points to serializable format
                for point in points_batch:
                    all_points.append({
                        "id": point.id,
                        "vector": point.vector,
                        "payload": point.payload
                    })
                
                offset = next_offset
                if next_offset is None:
                    break
            
            # Write to file
            with open(backup_file, 'w') as f:
                json.dump({
                    "company_id": company_id,
                    "collection_name": collection_name,
                    "backup_time": timestamp,
                    "points_count": len(all_points),
                    "points": all_points
                }, f)
            
            logger.info(f"Backed up {len(all_points)} points to {backup_file}")
            return backup_file
            
        except Exception as e:
            logger.error(f"Error backing up embeddings: {str(e)}")
            raise

"""
Key Improvements:

Connection Health Management:
Added client health checking with automatic reconnection
Added connection lock to prevent race conditions
Periodic health checks to maintain connection reliability


Dynamic Batch Sizing:
Implemented intelligent batch size adjustment based on success/failure
Added retry logic with exponential backoff for failed batch operations


Enhanced Filtering:
Added a helper method to build Qdrant filters from dictionaries
Added additional indexes for faster filtering


Better Caching:
Added TTL-based caching for vector stores
Added embedding cache for frequently used queries
Added proper cache invalidation when data changes


Search Improvements:
Enhanced search functionality with better filtering options
Added score threshold parameter for quality control
Improved result formatting for easier consumption


Pagination Support:
Added scrolling/pagination for search results
Implemented efficient retrieval of large result sets


Backup and Recovery:
Added backup_embeddings method to save data to local file
Structured backup for easier restoration


Convenience Methods:
Added load_documents method for easier document embedding
Added delete_points method with filter condition support


Error Handling:
More comprehensive error handling throughout
Better logging with context information
Graceful degradation when errors occur

These improvements make the QdrantService more robust, efficient, and reliable, especially when dealing with large datasets or unstable network connections. The service now handles errors more gracefully, manages resources more efficiently, and provides better control over search and retrieval operations
"""