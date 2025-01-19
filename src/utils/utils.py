"""
Features of utils.py:
Logging Utilities:

Centralized logging configuration with file rotation.
Supports daily log rotation and console output.
Redis Utilities:

init_redis: Initialize Redis connections.
check_and_update_rate_limit: Advanced rate-limiting mechanism.
JSON Utilities:

Safe loading (safe_json_loads) and dumping (safe_json_dumps) of JSON data with error handling.
Hashing Utilities:

Simple MD5 hash generator.
Date-Time Utilities:

Formatting and parsing of ISO datetime strings.
Retry Utilities:

Retry mechanism for async functions with configurable retries and exponential backoff.
General Helper Functions:

generate_unique_key: Creates a unique MD5 hash key based on multiple input strings.
This utils.py is designed to support a variety of general-purpose operations while adhering to the 
principles of robustness, modularity, and reusability. Let me know if you’d like to further enhance any part!
"""

import asyncio
import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from redis import asyncio as aioredis
from src.config.settings import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD


# ================================= Logging Utilities =================================
def configure_logger(log_file: str = "app.log") -> logging.Logger:
    """
    Configure and return a logger with both file and console handlers.
    Args:
        log_file (str): Path to the log file.
    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger("app_logger")
    logger.setLevel(logging.INFO)
    
    # Formatter for logs
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # File handler
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# ================================= Redis Utilities =================================
async def init_redis() -> aioredis.Redis:
    """
    Initialize and return an async Redis connection.
    Returns:
        aioredis.Redis: Redis connection instance.
    """
    if REDIS_PASSWORD:
        return await aioredis.from_url(
            f"redis://{REDIS_HOST}:{REDIS_PORT}",
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
    return await aioredis.from_url(
        f"redis://{REDIS_HOST}:{REDIS_PORT}",
        decode_responses=True,
    )


async def check_and_update_rate_limit(
    redis_conn: aioredis.Redis,
    user_id: str,
    agent_type: str,
    limit: int = 20,
    ttl: int = 7 * 24 * 60 * 60,
) -> bool:
    """
    Check and update rate limits for a user and agent type in Redis.
    Args:
        redis_conn (aioredis.Redis): Redis connection instance.
        user_id (str): User identifier.
        agent_type (str): Type of agent being accessed.
        limit (int): Maximum allowed interactions.
        ttl (int): Time-to-live for the rate limit key in seconds (default: 7 days).
    Returns:
        bool: True if within limit, False otherwise.
    """
    key = f"rate_limit:{user_id}:{agent_type}"
    now = datetime.utcnow()
    async with redis_conn.pipeline() as pipe:
        try:
            # Check if the key exists
            exists = await redis_conn.exists(key)
            if exists:
                current_count, last_reset = await redis_conn.hmget(key, "count", "last_reset")
                current_count = int(current_count or 0)
                last_reset = datetime.fromisoformat(last_reset) if last_reset else now

                if (now - last_reset).total_seconds() > ttl:
                    await pipe.hset(key, mapping={"count": 1, "last_reset": now.isoformat()}).expire(key, ttl).execute()
                    return True

                if current_count >= limit:
                    return False

                await pipe.hincrby(key, "count", 1).expire(key, ttl).execute()
                return True
            else:
                await pipe.hset(key, mapping={"count": 1, "last_reset": now.isoformat()}).expire(key, ttl).execute()
                return True
        except Exception as e:
            logging.error(f"Redis rate limit error: {str(e)}")
            return False


# ================================= JSON Utilities =================================
def safe_json_loads(json_string: str, default: Optional[Any] = None) -> Optional[Any]:
    """
    Safely load a JSON string into a Python object.
    Args:
        json_string (str): JSON string to parse.
        default (Optional[Any]): Default value to return if parsing fails.
    Returns:
        Optional[Any]: Parsed JSON object or default value.
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        logging.error("Failed to parse JSON string.")
        return default


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """
    Safely convert a Python object to a JSON string.
    Args:
        obj (Any): Python object to serialize.
        indent (int): Number of spaces for indentation.
    Returns:
        str: JSON string representation of the object.
    """
    try:
        return json.dumps(obj, indent=indent)
    except (TypeError, ValueError) as e:
        logging.error(f"Failed to serialize object to JSON: {e}")
        return "{}"


# ================================= Hashing Utilities =================================
def generate_md5_hash(content: str) -> str:
    """
    Generate an MD5 hash of a given string.
    Args:
        content (str): Input string to hash.
    Returns:
        str: MD5 hash of the input string.
    """
    return hashlib.md5(content.encode()).hexdigest()


# ================================= Date-Time Utilities =================================
def format_datetime(dt: datetime) -> str:
    """
    Format a datetime object into ISO format.
    Args:
        dt (datetime): Datetime object to format.
    Returns:
        str: ISO-formatted datetime string.
    """
    return dt.isoformat()


def parse_iso_datetime(iso_string: str) -> Optional[datetime]:
    """
    Parse an ISO-formatted datetime string.
    Args:
        iso_string (str): ISO datetime string to parse.
    Returns:
        Optional[datetime]: Parsed datetime object or None if parsing fails.
    """
    try:
        return datetime.fromisoformat(iso_string)
    except ValueError:
        logging.error(f"Failed to parse ISO datetime string: {iso_string}")
        return None


# ================================= Retry Utilities =================================
async def retry_async_function(
    func: callable,
    *args,
    retries: int = 3,
    delay: float = 0.5,
    **kwargs
) -> Any:
    """
    Retry an asynchronous function on failure.
    Args:
        func (callable): The async function to retry.
        *args: Positional arguments for the function.
        retries (int): Number of retries before failing.
        delay (float): Delay between retries in seconds.
        **kwargs: Keyword arguments for the function.
    Returns:
        Any: Result of the function call.
    """
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logging.warning(f"Retry {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
            else:
                raise


# ================================= General Helper Functions =================================
def generate_unique_key(*args: str) -> str:
    """
    Generate a unique key by hashing multiple input strings.
    Args:
        *args (str): Strings to include in the key.
    Returns:
        str: A unique key.
    """
    return generate_md5_hash("_".join(args))
