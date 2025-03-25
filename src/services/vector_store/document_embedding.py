from typing import List, Dict, Any, Optional, Generator
import logging
from datetime import datetime
import uuid
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_openai import OpenAIEmbeddings
from qdrant_client import models
import asyncio
import PyPDF2
from io import BytesIO

logger = logging.getLogger(__name__)

class DocumentEmbeddingService:
    def __init__(self, qdrant_service):
        """Initialize Document Embedding Service"""
        self.qdrant_service = qdrant_service
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small"
        )
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,  # Optimized chunk size for precise retrieval
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
            keep_separator=True
        )
    
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from a PDF using PyPDF2."""
        try:
            reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            return ""
    
    def extract_text_from_document(self, content: Any, file_type: str) -> str:
        """Extract text from different document types with better encoding handling"""
        try:
            if isinstance(content, bytes):
                if file_type == "application/pdf":
                    return self.extract_text_from_pdf(content)
                elif file_type.startswith("text/"):
                    # Try different encodings for text files
                    encodings = ["utf-8", "latin-1", "cp1252"]
                    for encoding in encodings:
                        try:
                            return content.decode(encoding)
                        except UnicodeDecodeError:
                            continue
                    # If all encodings fail, use replace mode
                    return content.decode("utf-8", errors="replace")
                else:
                    # Default to UTF-8 text with replace mode
                    return content.decode("utf-8", errors="replace")
            elif isinstance(content, str):
                return content
            else:
                logger.warning(f"Unsupported content type: {type(content)}")
                return str(content)
        except Exception as e:
            logger.error(f"Error extracting text: {str(e)}")
            return ""
    
    async def process_documents(self, documents: List[Dict[str, Any]], max_size_mb: int = 10) -> List[Document]:
        """Process documents into chunks with metadata"""
        processed_docs = []
        for doc in documents:
            content = doc['content']
            file_type = doc['metadata'].get('file_type', 'text/plain')
            
            # Check document size
            if isinstance(content, bytes) and len(content) > max_size_mb * 1024 * 1024:
                logger.warning(f"Document {doc.get('id')} exceeds size limit of {max_size_mb}MB, skipping")
                continue
            
            # Extract text based on file type
            text = self.extract_text_from_document(content, file_type)
            logger.info(f"Extracted text from {file_type} document (first 200 chars): {text[:200]}")
            
            if not text:
                logger.warning(f"No text extracted from document {doc.get('id')}")
                continue
            
            # Split the extracted text into chunks
            chunks = self.text_splitter.split_text(text)
            for i, chunk in enumerate(chunks):
                metadata = {
                    **doc.get('metadata', {}),
                    'chunk_id': i,
                    'total_chunks': len(chunks),
                    'doc_id': doc.get('id'),
                    'processed_at': datetime.utcnow().isoformat()
                }
                processed_docs.append(Document(page_content=chunk, metadata=metadata))
        
        return processed_docs
    
    async def process_large_document(self, document: Dict[str, Any], chunk_size: int = 1024 * 1024) -> Generator[Document, None, None]:
        """Process a large document in chunks to avoid memory issues"""
        content = document['content']
        file_type = document['metadata'].get('file_type', 'text/plain')
        doc_id = document.get('id')
        
        if not isinstance(content, bytes):
            # If not bytes, process normally
            text = self.extract_text_from_document(content, file_type)
            chunks = self.text_splitter.split_text(text)
            for i, chunk in enumerate(chunks):
                yield Document(
                    page_content=chunk, 
                    metadata={
                        **document.get('metadata', {}),
                        'chunk_id': i,
                        'total_chunks': len(chunks),
                        'doc_id': doc_id,
                        'processed_at': datetime.utcnow().isoformat()
                    }
                )
        else:
            # For binary content, process in chunks
            if file_type == "application/pdf":
                # For PDFs, process page by page
                reader = PyPDF2.PdfReader(BytesIO(content))
                text = ""
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                    
                    # Process accumulated text when it reaches chunk_size
                    if len(text) >= chunk_size:
                        chunks = self.text_splitter.split_text(text)
                        for j, chunk in enumerate(chunks):
                            yield Document(
                                page_content=chunk, 
                                metadata={
                                    **document.get('metadata', {}),
                                    'chunk_id': f"{i}-{j}",
                                    'doc_id': doc_id,
                                    'processed_at': datetime.utcnow().isoformat()
                                }
                            )
                        text = ""  # Reset accumulated text
                
                # Process any remaining text
                if text:
                    chunks = self.text_splitter.split_text(text)
                    for j, chunk in enumerate(chunks):
                        yield Document(
                            page_content=chunk, 
                            metadata={
                                **document.get('metadata', {}),
                                'chunk_id': f"final-{j}",
                                'doc_id': doc_id,
                                'processed_at': datetime.utcnow().isoformat()
                            }
                        )
            else:
                # For other binary formats, process in fixed-size chunks
                stream = BytesIO(content)
                buffer_size = chunk_size
                buffer = stream.read(buffer_size)
                chunk_index = 0
                
                while buffer:
                    text = self.extract_text_from_document(buffer, file_type)
                    if text:
                        chunks = self.text_splitter.split_text(text)
                        for j, chunk in enumerate(chunks):
                            yield Document(
                                page_content=chunk, 
                                metadata={
                                    **document.get('metadata', {}),
                                    'chunk_id': f"{chunk_index}-{j}",
                                    'doc_id': doc_id,
                                    'processed_at': datetime.utcnow().isoformat()
                                }
                            )
                    
                    chunk_index += 1
                    buffer = stream.read(buffer_size)
    
    async def embed_documents(
        self, 
        company_id: str, 
        agent_id: str,
        documents: List[Dict[str, Any]]
    ) -> bool:
        """Embed documents and store in vector database"""
        try:
            logger.info(f"Embedding {len(documents)} documents for agent {agent_id}")
            
            # Process documents into chunks
            processed_docs = await self.process_documents(documents)
            
            if not processed_docs:
                logger.warning("No documents processed successfully")
                return True
            
            # Process in batches
            batch_size = 5  # Adjust based on your use case
            total_points = 0
            
            for i in range(0, len(processed_docs), batch_size):
                batch = processed_docs[i:i+batch_size]
                
                # Create batch embedding tasks
                embedding_tasks = []
                for doc in batch:
                    embedding_tasks.append(self.embed_with_retries(doc.page_content))
                
                # Execute batch embeddings concurrently
                batch_embeddings = await asyncio.gather(*embedding_tasks, return_exceptions=True)
                
                batch_points = []
                for j, embedding_result in enumerate(batch_embeddings):
                    if isinstance(embedding_result, Exception):
                        logger.error(f"Embedding failed: {str(embedding_result)}")
                        continue
                        
                    doc = batch[j]
                    batch_points.append(models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=embedding_result,
                        payload={
                            'page_content': doc.page_content,
                            'metadata': doc.metadata,
                            'agent_id': agent_id,
                            'type': 'document'
                        }
                    ))
                
                # Add batch to Qdrant
                if batch_points:
                    result = await self.qdrant_service.add_points(company_id, batch_points)
                    if not result:
                        logger.error(f"Failed to add batch {i//batch_size + 1} to Qdrant")
                        return False
                    
                    total_points += len(batch_points)
                
                logger.info(f"Processed batch {i//batch_size + 1}/{(len(processed_docs) + batch_size - 1)//batch_size}")
            
            logger.info(f"Embedded {total_points} document chunks for agent {agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error embedding documents: {str(e)}")
            return False
    
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
    
    async def replace_document_embeddings(
        self,
        company_id: str,
        agent_id: str,
        document_id: str,
        new_content: Any,
        file_type: str
    ) -> bool:
        """Replace embeddings for an existing document"""
        try:
            # Delete existing vectors for this document
            filter_condition = {
                "metadata.doc_id": document_id
            }
            
            # Delete existing points
            deletion_result = await self.qdrant_service.delete_points(
                company_id, 
                filter_condition
            )
            
            if not deletion_result:
                logger.warning(f"No existing embeddings found for document {document_id}")
            
            # Process and embed the new document
            text = self.extract_text_from_document(new_content, file_type)
            if not text:
                return False
                
            # Create a document object with the new content
            document = {
                'id': document_id,
                'content': text,
                'metadata': {
                    'file_type': file_type,
                    'doc_id': document_id,
                    'agent_id': agent_id,
                    'updated_at': datetime.utcnow().isoformat()
                }
            }
            
            # Embed the new document
            return await self.embed_documents(company_id, agent_id, [document])
            
        except Exception as e:
            logger.error(f"Error replacing document embeddings: {str(e)}")
            return False
    
    async def process_and_embed_large_document(
        self,
        company_id: str,
        agent_id: str,
        document: Dict[str, Any],
        batch_size: int = 10
    ) -> bool:
        """Process and embed a large document using streaming to manage memory"""
        try:
            logger.info(f"Processing large document {document.get('id')} for agent {agent_id}")
            
            doc_processor = self.process_large_document(document)
            
            # Process document in chunks and embed in batches
            batch = []
            total_chunks = 0
            batch_count = 0
            
            async for doc_chunk in doc_processor:
                batch.append(doc_chunk)
                
                if len(batch) >= batch_size:
                    # Process the current batch
                    embedding_tasks = [self.embed_with_retries(doc.page_content) for doc in batch]
                    embeddings = await asyncio.gather(*embedding_tasks, return_exceptions=True)
                    
                    # Create points for valid embeddings
                    points = []
                    for i, embed_result in enumerate(embeddings):
                        if isinstance(embed_result, Exception):
                            logger.error(f"Embedding failed: {str(embed_result)}")
                            continue
                            
                        doc = batch[i]
                        points.append(models.PointStruct(
                            id=str(uuid.uuid4()),
                            vector=embed_result,
                            payload={
                                'page_content': doc.page_content,
                                'metadata': doc.metadata,
                                'agent_id': agent_id,
                                'type': 'document'
                            }
                        ))
                    
                    # Store points in vector DB
                    if points:
                        success = await self.qdrant_service.add_points(company_id, points)
                        if not success:
                            logger.error(f"Failed to add batch {batch_count} to vector store")
                            return False
                            
                        total_chunks += len(points)
                    
                    batch_count += 1
                    logger.info(f"Processed batch {batch_count} with {len(points)} chunks")
                    
                    # Clear batch for next iteration
                    batch = []
            
            # Process any remaining chunks
            if batch:
                embedding_tasks = [self.embed_with_retries(doc.page_content) for doc in batch]
                embeddings = await asyncio.gather(*embedding_tasks, return_exceptions=True)
                
                points = []
                for i, embed_result in enumerate(embeddings):
                    if isinstance(embed_result, Exception):
                        continue
                        
                    doc = batch[i]
                    points.append(models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=embed_result,
                        payload={
                            'page_content': doc.page_content,
                            'metadata': doc.metadata,
                            'agent_id': agent_id,
                            'type': 'document'
                        }
                    ))
                
                if points:
                    success = await self.qdrant_service.add_points(company_id, points)
                    if not success:
                        logger.error(f"Failed to add final batch to vector store")
                        return False
                        
                    total_chunks += len(points)
                    
                    batch_count += 1
                    logger.info(f"Processed final batch {batch_count} with {len(points)} chunks")
            
            logger.info(f"Successfully processed large document into {total_chunks} embedded chunks")
            return True
            
        except Exception as e:
            logger.error(f"Error processing large document: {str(e)}")
            return False
            
    async def get_document_chunks(
        self,
        company_id: str,
        document_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Retrieve all chunks for a specific document"""
        try:
            filter_condition = {
                "metadata.doc_id": document_id
            }
            
            chunks = await self.qdrant_service.search_by_filter(
                company_id,
                filter_condition,
                limit=limit
            )
            
            return chunks
        except Exception as e:
            logger.error(f"Error retrieving document chunks: {str(e)}")
            return []

"""
This updated code includes:
- Error Handling for Embeddings: Added embed_with_retries method with exponential backoff to handle API failures gracefully.
- Batch Processing: Implemented batched processing for documents to improve efficiency.
- File Size Limits: Added size checking to avoid processing excessively large documents.
- Better Text Extraction: Improved encoding handling for text extraction from various file types.
- Document Update Support: Added replace_document_embeddings method to update existing documents.
- Memory Management for Large Documents: Added process_large_document and process_and_embed_large_document methods to handle large files without excessive memory consumption.
- Agent ID in Metadata: Included agent_id in the payload for better filtering.
- Document Chunk Retrieval: Added a method to retrieve all chunks for a specific document.
- Streaming Processing: Implemented asynchronous streaming for document processing to improve memory efficiency.
- Better Logging: Enhanced logging throughout the code for better troubleshooting.
- Flexible Encoding Support: Added multi-encoding attempts to better handle various text files.
"""