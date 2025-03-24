# services/data_loaders.py

import os
from typing import List, Dict, Any, Optional
import pandas as pd
from sqlalchemy import create_engine, inspect, MetaData
from sqlalchemy.schema import Table
from sqlalchemy.sql import select
import logging
from datetime import datetime
import asyncio
import aiofiles
from pathlib import Path
import magic  # for file type detection
import textract
from bs4 import BeautifulSoup
import json
from urllib.parse import quote_plus


logger = logging.getLogger(__name__)

class DocumentLoader:
    """Handles loading and processing various document types"""
    
    SUPPORTED_EXTENSIONS = {
        '.txt', '.pdf', '.docx', '.doc', '.html', 
        '.md', '.json', '.csv', '.xlsx'
    }
    
    def __init__(self):
        self.mime = magic.Magic(mime=True)
    
    async def load_document(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Load and process a document file"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
                
            file_ext = Path(file_path).suffix.lower()
            if file_ext not in self.SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported file type: {file_ext}")
            
            # Get file mime type
            mime_type = self.mime.from_file(file_path)
            
            # Extract text based on file type
            if file_ext in ['.txt', '.md']:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
            
            elif file_ext == '.pdf':
                try:
                    content = await asyncio.wait_for(
                        asyncio.to_thread(
                            textract.process,
                            file_path,
                            method='pdfminer'
                        ),
                        timeout=300.0  # 300 second timeout
                    )
                    content = content.decode('utf-8')
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"PDF extraction with pdfminer failed: {e}, trying alternative method")
                    try:
                        # Fallback to another method
                        content = await asyncio.wait_for(
                            asyncio.to_thread(
                                textract.process,
                                file_path
                            ),
                            timeout=60.0
                        )
                        content = content.decode('utf-8')
                    except (asyncio.TimeoutError, Exception) as e2:
                        logger.error(f"All PDF extraction methods failed: {e2}")
                        return None
            
            elif file_ext in ['.docx', '.doc']:
                try:
                    content = await asyncio.wait_for(
                        asyncio.to_thread(textract.process, file_path),
                        timeout=60.0  # 60 second timeout
                    )
                    content = content.decode('utf-8')
                except asyncio.TimeoutError:
                    logger.error(f"Document processing timed out for {file_path}")
                    return None
                except Exception as e:
                    logger.error(f"Error processing document {file_path}: {e}")
                    return None
            
            elif file_ext == '.html':
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    html_content = await f.read()
                soup = BeautifulSoup(html_content, 'html.parser')
                content = soup.get_text(separator=' ')
            
            elif file_ext == '.json':
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    json_content = await f.read()
                content = json.dumps(json.loads(json_content))
            
            elif file_ext in ['.csv', '.xlsx']:
                try:
                    if file_ext == '.csv':
                        df = await asyncio.to_thread(pd.read_csv, file_path)
                    else:
                        df = await asyncio.to_thread(pd.read_excel, file_path)
                    content = df.to_string()
                except Exception as e:
                    logger.error(f"Error processing {file_ext} file {file_path}: {e}")
                    return None
            
            return {
                'id': os.path.basename(file_path),
                'content': content,
                'metadata': {
                    'filename': os.path.basename(file_path),
                    'file_type': file_ext,
                    'mime_type': mime_type,
                    'size': os.path.getsize(file_path),
                    'last_modified': datetime.fromtimestamp(
                        os.path.getmtime(file_path)
                    ).isoformat()
                },
                'doc_type': 'document'
            }
            
        except Exception as e:
            logger.error(f"Error loading document {file_path}: {str(e)}")
            return None

    async def load_directory(
        self,
        directory_path: str,
        recursive: bool = True
    ) -> List[Dict[str, Any]]:
        """Load all supported documents from a directory"""
        documents = []
        try:
            directory_path = os.path.abspath(directory_path)
            for root, _, files in os.walk(directory_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if Path(file).suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        doc = await self.load_document(file_path)
                        if doc:
                            documents.append(doc)
                
                if not recursive:
                    break
                    
            return documents
            
        except Exception as e:
            logger.error(f"Error loading directory {directory_path}: {str(e)}")
            return []

class DatabaseLoader:
    """Handles loading and processing database tables"""
    
    def __init__(self):
        self.supported_databases = {
            'postgresql': 'postgresql://',
            'mysql': 'mysql://',
            'mssql': 'mssql://',
            'oracle': 'oracle://',
            'sqlite': 'sqlite:///'
        }
    
    async def create_connection(
        self,
        db_type: str,
        connection_params: Dict[str, Any]
    ) -> Any:
        """Create database connection"""
        try:
            if db_type not in self.supported_databases:
                raise ValueError(f"Unsupported database type: {db_type}")
            
            # Construct connection URL based on database type
            if db_type == 'sqlite':
                connection_url = f"{self.supported_databases[db_type]}{connection_params['database']}"
            else:
                connection_url = (
                    f"{self.supported_databases[db_type]}"
                    f"{connection_params.get('username', '')}:"
                    f"{quote_plus(connection_params.get('password', ''))}@"
                    f"{connection_params.get('host', 'localhost')}:"
                    f"{connection_params.get('port', '')}/"
                    f"{connection_params.get('database', '')}"
                )
            
            # Create engine
            engine = create_engine(connection_url)
            
            return engine
            
        except Exception as e:
            logger.error(f"Error creating database connection: {str(e)}")
            raise

    async def get_table_schema(self, engine: Any, table_name: str) -> Dict[str, Any]:
        """Get schema information for a specific table"""
        try:
            inspector = inspect(engine)
            
            if table_name not in inspector.get_table_names():
                raise ValueError(f"Table {table_name} not found in database")
            
            columns = inspector.get_columns(table_name)
            primary_keys = inspector.get_primary_keys(table_name)
            foreign_keys = inspector.get_foreign_keys(table_name)
            
            return {
                'columns': columns,
                'primary_keys': primary_keys,
                'foreign_keys': foreign_keys
            }
            
        except Exception as e:
            logger.error(f"Error getting schema for table {table_name}: {str(e)}")
            raise

    async def load_table_data(
        self,
        engine: Any,
        table_name: str,
        batch_size: int = 1000,
        custom_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Load data from a database table"""
        try:
            # Get total count for batching
            with engine.connect() as conn:
                logger.warning(f"Using custom query which bypasses SQL injection protection: {custom_query}")
                if custom_query:
                    query = custom_query
                else:
                    # Use SQLAlchemy's Table object and select construct
                    metadata = MetaData()
                    table = Table(table_name, metadata, autoload_with=engine)
                    query = select([table])
                
                # Execute query in batches
                data = []
                try:
                    df_iterator = pd.read_sql(
                        query,
                        conn,
                        chunksize=batch_size
                    )
                    
                    for chunk in df_iterator:
                        records = chunk.to_dict('records')
                        data.extend(records)
                finally:
                    # Ensure the iterator is closed
                    if 'df_iterator' in locals():
                        df_iterator.close()
                
                return data
                
        except Exception as e:
            logger.error(f"Error loading data from table {table_name}: {str(e)}")
            raise

    async def process_table_data(
        self,
        table_data: List[Dict[str, Any]],
        schema_mapping: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Process table data into a format suitable for vector storage"""
        try:
            processed_data = []
            
            for record in table_data:
                # Create semantic text representation
                semantic_parts = []
                
                for col_name, semantic_name in schema_mapping.items():
                    if col_name in record:
                        value = record[col_name]
                        if pd.notna(value):  # Handle NULL/NaN values
                            semantic_parts.append(f"{semantic_name}: {value}")
                
                if semantic_parts:
                    processed_data.append({
                        'id': str(record.get('id', hash(str(record)))),
                        'content': '. '.join(semantic_parts),
                        'metadata': {
                            'original_record': record,
                            'schema_mapping': schema_mapping
                        },
                        'doc_type': 'database_record'
                    })
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Error processing table data: {str(e)}")
            raise

    async def validate_connection(self, engine: Any) -> bool:
        """Validate database connection"""
        try:
            with engine.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Connection validation failed: {str(e)}")
            return False

    async def load_database(
        self,
        connection_params: Dict[str, Any],
        tables_config: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Load and process multiple tables from a database
        
        tables_config format:
        [
            {
                'table_name': 'customers',
                'schema_mapping': {'id': 'Customer ID', 'name': 'Customer Name', ...},
                'custom_query': 'SELECT * FROM customers WHERE active = true'  # Optional
            },
            ...
        ]
        """
        try:
            engine = await self.create_connection(
                connection_params['type'],
                connection_params
            )
            
            if not await self.validate_connection(engine):
                raise Exception("Failed to validate database connection")
            
            all_data = []
            
            for table_config in tables_config:
                table_name = table_config['table_name']
                schema_mapping = table_config['schema_mapping']
                custom_query = table_config.get('custom_query')
                
                # Load raw data
                raw_data = await self.load_table_data(
                    engine,
                    table_name,
                    custom_query=custom_query
                )
                
                # Process data
                processed_data = await self.process_table_data(
                    raw_data,
                    schema_mapping
                )
                
                all_data.extend(processed_data)
            
            return all_data
            
        except Exception as e:
            logger.error(f"Error loading database: {str(e)}")
            raise
        finally:
            if 'engine' in locals():
                engine.dispose()

"""
Changes made by Sai:
SQL Injection Protection:

Added proper use of SQLAlchemy's Table and select constructs instead of string-based SQL queries
Warning for custom SQL queries that bypass protections

Password Security:
Added URL encoding for database passwords using quote_plus

Path Traversal Protection:
Added os.path.abspath() to canonicalize file paths

Error Handling and Robustness:
Better PDF Processing:
Added fallback mechanism for PDF extraction when the primary method fails
Enhanced error handling for document processing

Timeout Controls:
Added timeouts for potentially long-running operations using asyncio.wait_for()
Separate timeouts for different document types (300s for PDFs, 60s for other document types)

Resource Management:
Added proper cleanup for database iterators
Ensured engine disposal in a finally block
Better handling of connection failures

Exception Handling:
More specific exception types for better error classification
Enhanced logging for different error scenarios
Added error handling for CSV and Excel file processing

Performance Improvements:
Async Processing:
Proper use of asyncio.to_thread() for CPU-bound operations
Better async file reading with aiofiles

Database Interaction:
Added chunked processing for database queries
Properly handling iterators for data frames

Code Structure and Maintainability:

Imports:
Added missing imports (MetaData, quote_plus)
Better organization of imports


Documentation:
Expanded docstrings and comments
Better documentation of parameters and return values

The code still has a few remaining issues:

Warning Logging Bug:

The load_table_data method always logs a warning about custom queries bypassing SQL injection protection, even when no custom query is provided.

pythonCopylogger.warning(f"Using custom query which bypasses SQL injection protection: {custom_query}")
if custom_query:
    query = custom_query
This should only be logged when a custom query is actually used.
Memory Management:

It's still missing memory limits for large datasets as recommended earlier.


Inefficient Document Processing:

Processing a large number of files in a directory is still done sequentially, which could be inefficient for large directories.


Security for Directory Traversal:

While it does use os.path.abspath(), there's still no restriction to specific allowed roots.



The other improvements look good:

Proper SQL query construction with SQLAlchemy
Password escaping in database URLs
Better error handling and timeouts for document processing
Proper resource cleanup

Most critical security issues have been addressed, but these remaining items would further improve robustness and performance.
"""