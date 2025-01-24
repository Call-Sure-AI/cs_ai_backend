import logging
import logging.handlers
import os
import json
from datetime import datetime
from typing import Any, Dict
from functools import wraps
import time

from config.settings import LOG_DIR, LOG_LEVEL, DEBUG

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# Define log formats
CONSOLE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
FILE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'

def setup_logging():
    """Configure logging for the application"""
    # Create formatters
    console_formatter = logging.Formatter(CONSOLE_FORMAT)
    file_formatter = logging.Formatter(FILE_FORMAT)

    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)

    # Rotating file handler - 10MB per file, keep 30 days of logs
    file_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, 'app.log'),
        when='midnight',
        interval=1,
        backupCount=30
    )
    file_handler.setFormatter(file_formatter)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Create separate WebRTC log file
    webrtc_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, 'webrtc.log'),
        when='midnight',
        interval=1,
        backupCount=30
    )
    webrtc_handler.setFormatter(file_formatter)

    # Set up WebRTC logger
    webrtc_logger = logging.getLogger('webrtc')
    webrtc_logger.setLevel(LOG_LEVEL)
    webrtc_logger.addHandler(webrtc_handler)
    
    # Suppress logs from libraries if not in debug mode
    if not DEBUG:
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('websockets').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name"""
    return logging.getLogger(name)

class WebRTCLogger:
    """Custom logger for WebRTC-specific events"""
    def __init__(self, peer_id: str = None, company_id: str = None):
        self.logger = logging.getLogger('webrtc')
        self.peer_id = peer_id
        self.company_id = company_id

    def _format_message(self, message: str, extra: Dict[str, Any] = None) -> str:
        """Format log message with peer and company info"""
        context = []
        if self.peer_id:
            context.append(f"peer_id={self.peer_id}")
        if self.company_id:
            context.append(f"company_id={self.company_id}")
        if extra:
            context.extend([f"{k}={v}" for k, v in extra.items()])
            
        context_str = ' '.join(context)
        return f"{message} [{context_str}]" if context_str else message

    def info(self, message: str, extra: Dict[str, Any] = None):
        self.logger.info(self._format_message(message, extra))

    def debug(self, message: str, extra: Dict[str, Any] = None):
        self.logger.debug(self._format_message(message, extra))

    def warning(self, message: str, extra: Dict[str, Any] = None):
        self.logger.warning(self._format_message(message, extra))

    def error(self, message: str, extra: Dict[str, Any] = None):
        self.logger.error(self._format_message(message, extra))

def log_timing(logger: logging.Logger = None):
    """Decorator to log function execution time"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                (logger or logging.getLogger()).debug(
                    f"{func.__name__} completed in {execution_time:.3f}s"
                )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                (logger or logging.getLogger()).error(
                    f"{func.__name__} failed after {execution_time:.3f}s: {str(e)}"
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                (logger or logging.getLogger()).debug(
                    f"{func.__name__} completed in {execution_time:.3f}s"
                )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                (logger or logging.getLogger()).error(
                    f"{func.__name__} failed after {execution_time:.3f}s: {str(e)}"
                )
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

# Example usage:
# logger = WebRTCLogger(peer_id="peer123", company_id="company456")
# logger.info("Connection established", {"latency": "150ms"})
# 
# @log_timing()
# async def some_function():
#     await asyncio.sleep(1)
#     return "done"
# ============================================================================================================
# # In your WebRTC handlers
# from utils.logger import WebRTCLogger, log_timing

# logger = WebRTCLogger(peer_id="123", company_id="456")
# logger.info("Peer connected", {"ip": "192.168.1.1"})

# @log_timing()
# async def handle_connection(websocket):
#     # Function timing will be logged
#     pass

"""
comprehensive logger.py that includes:

Basic Logging Setup:

Console and file logging
Rotating log files (30 days retention)
Different formats for console and file output
Log level configuration from settings


WebRTC-Specific Features:

Dedicated WebRTC log file
Custom WebRTCLogger class for peer/company context
Formatted WebRTC logs with additional metadata


Utility Functions:

setup_logging(): Initialize logging configuration
get_logger(): Get logger instances
log_timing: Decorator for performance monitoring


Features:

Automatic log rotation
Debug mode support
Library log suppression in production
Structured logging for WebRTC events
Performance tracking
Exception handling



# Example usage:
# logger = WebRTCLogger(peer_id="peer123", company_id="company456")
# logger.info("Connection established", {"latency": "150ms"})
# 
# @log_timing()
# async def some_function():
#     await asyncio.sleep(1)
#     return "done"


# In your WebRTC handlers
from utils.logger import WebRTCLogger, log_timing

logger = WebRTCLogger(peer_id="123", company_id="456")
logger.info("Peer connected", {"ip": "192.168.1.1"})

@log_timing()
async def handle_connection(websocket):
    # Function timing will be logged
    pass
"""