# src/database/config.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus
import logging
from contextlib import contextmanager
import sqlalchemy.exc

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Loading environment variables from {dotenv_path}")
load_dotenv(dotenv_path)

# Create declarative base
Base = declarative_base()

def get_database_url():
    """Create database URL with proper encoding"""
    user = os.getenv("DATABASE_USER")
    password = os.getenv("DATABASE_PASSWORD")
    host = os.getenv("DATABASE_HOST")
    database = os.getenv("DATABASE_NAME")
    
    if not all([user, password, host, database]):
        raise ValueError("Missing database configuration. Please check your .env file.")
    
    # Encode the password to handle special characters
    encoded_password = quote_plus(password)
    
    return os.getenv("DATABASE_URL")

def create_db_engine():
    """Create database engine with proper configuration"""
    try:
        database_url = os.getenv("DATABASE_URL")
        logger.info(f"Creating database engine with URL: {database_url}")
        logger.info(f"Connecting to database: {database_url.split('@')[1]}")  # Log only host part
        
        engine = create_engine(
            database_url,
            pool_size=10,              # Increased from 5
            max_overflow=20,           # Increased from 10
            pool_timeout=30,
            pool_recycle=600,          # Reduced from 1800 (30 minutes → 10 minutes)
            pool_pre_ping=True,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 60,
                "application_name": "ai_closer_app",
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5
            }
        )
        return engine
    except Exception as e:
        logger.error(f"Error creating database engine: {str(e)}")
        raise

# Create engine and session factory
try:
    engine = create_db_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.error(f"Failed to initialize database: {str(e)}")
    raise

def get_db():
    """Database session dependency with improved error handling for WebSockets"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {str(e)}")
        # Make sure we rollback on exception
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        # Safely close the session
        try:
            db.close()
        except sqlalchemy.exc.OperationalError as e:
            # Handle SSL connection errors gracefully
            if "SSL connection has been closed unexpectedly" in str(e):
                logger.warning("SSL connection was already closed, ignoring")
            else:
                logger.warning(f"Error closing database connection: {str(e)}")
        except Exception as e:
            logger.warning(f"Error closing database connection: {str(e)}")

# For long-running processes like WebSockets, use a specific session manager
@contextmanager
def get_websocket_db():
    """Special database session for WebSocket handlers"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"WebSocket database session error: {str(e)}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"Error closing WebSocket database connection: {str(e)}")

# Export all necessary components
__all__ = ['engine', 'SessionLocal', 'Base', 'get_db', 'get_websocket_db']