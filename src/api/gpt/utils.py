"""
The src/api/gpt/utils.py file should house utility functions that enhance the
functionality of service.py but are not directly tied to the core operations
like calling GPT or generating embeddings. Instead, these utilities should focus
on operations such as message formatting, validation, token counting, and
handling error scenarios.

Utility functions for GPT-related operations, such as validating inputs,
constructing message templates, and rate limiting checks.

Features in This Updated Version:
    - Validation Functions: Ensure GPT message inputs are well-formed with validate_gpt_message_format.
    - Template Construction: Simplifies creating system, user, and assistant messages with specific helper functions.
    - Text Processing: Added split_text_into_chunks for breaking large inputs into manageable chunks. Extract key phrases with extract_key_phrases.
    - Rate Limiting: RateLimiter class to track and manage API usage.
    - S3 Logging and Upload: Includes log_and_upload_to_s3 for saving logs both locally and on S3.
    - Security: Added mask_sensitive_information to hide sensitive data (e.g., API keys) when logging or debugging.
    - This design keeps the utility functions focused, modular, and ready for integration across your GPT-related services.
"""

import re
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging
from src.services.storage.s3_storage import async_upload_to_s3


# ================================= Validation Functions =================================

def validate_gpt_message_format(messages: List[Dict[str, str]]) -> bool:
    """
    Validate the format of GPT messages.
    
    Args:
        messages (List[Dict[str, str]]): List of message dictionaries.
            Each dictionary must contain "role" and "content" keys.
    
    Returns:
        bool: True if all messages are valid, False otherwise.
    """
    if not isinstance(messages, list):
        logging.error("Messages should be a list.")
        return False

    for message in messages:
        if not isinstance(message, dict):
            logging.error("Each message should be a dictionary.")
            return False
        if "role" not in message or "content" not in message:
            logging.error("Each message must contain 'role' and 'content' keys.")
            return False
        if message["role"] not in {"developer", "user", "assistant"}:
            logging.error(f"Invalid role in message: {message['role']}")
            return False
        if not isinstance(message["content"], str):
            logging.error(f"Message content must be a string: {message['content']}")
            return False

    return True


# ================================= Template Construction =================================

def construct_gpt_developer_message(prompt: str) -> Dict[str, str]:
    """
    Construct a system message for GPT conversations.
    
    Args:
        prompt (str): The developer prompt to guide GPT behavior.
    
    Returns:
        Dict[str, str]: A dictionary with "role" and "content".
    """
    return {"role": "developer", "content": prompt}


def construct_gpt_user_message(content: str) -> Dict[str, str]:
    """
    Construct a user message for GPT conversations.
    
    Args:
        content (str): The user's input message.
    
    Returns:
        Dict[str, str]: A dictionary with "role" and "content".
    """
    return {"role": "user", "content": content}


def construct_gpt_assistant_message(content: str) -> Dict[str, str]:
    """
    Construct an assistant message for GPT conversations.
    
    Args:
        content (str): The assistant's response message.
    
    Returns:
        Dict[str, str]: A dictionary with "role" and "content".
    """
    return {"role": "assistant", "content": content}


# ================================= Helper Functions =================================

def split_text_into_chunks(text: str, max_length: int = 4096) -> List[str]:
    """
    Split a long text into smaller chunks, ensuring each chunk does not exceed the max length.
    
    Args:
        text (str): The input text to split.
        max_length (int): Maximum allowed length for each chunk. Default is 2048.
    
    Returns:
        List[str]: A list of text chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    while len(text) > max_length:
        split_at = text.rfind(' ', 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    chunks.append(text)
    return chunks


# ================================= Logging and Reporting =================================

async def log_and_upload_to_s3(bucket: str, key: str, log_data: str) -> None:
    """
    Log data locally and upload it to S3.
    
    Args:
        bucket (str): The S3 bucket name.
        key (str): The S3 object key.
        log_data (str): Log content to be uploaded.
    
    Returns:
        None
    """
    try:
        # Log locally
        logging.info(f"Log data: {log_data}")
        
        # Upload log data to S3
        await async_upload_to_s3(bucket, key, log_data.encode('utf-8'), content_type="text/plain")
        logging.info(f"Log successfully uploaded to S3: s3://{bucket}/{key}")
    except Exception as e:
        logging.error(f"Error logging and uploading to S3: {e}")


# ================================= Token and Security =================================

def mask_sensitive_information(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mask sensitive information in a dictionary, such as API keys or passwords.
    
    Args:
        data (Dict[str, Any]): Input data dictionary.
    
    Returns:
        Dict[str, Any]: A dictionary with sensitive values masked.
    """
    masked_data = {}
    for key, value in data.items():
        if "key" in key.lower() or "password" in key.lower():
            masked_data[key] = "****"
        else:
            masked_data[key] = value
    return masked_data
