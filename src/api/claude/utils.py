import re
from typing import List, Dict, Any
import logging
from src.services.storage.s3_storage import async_upload_to_s3

# ================================= Validation Functions =================================

def validate_claude_message_format(messages: List[Dict[str, str]]) -> bool:
    """
    Validate the format of Claude messages.

    Note: Claude only supports "user" and "assistant" roles directly.
    If a "system" message is included, it should be pre-formatted separately.
    
    Args:
        messages (List[Dict[str, str]]): List of messages.

    Returns:
        bool: True if valid, False otherwise.
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
        if message["role"] not in {"user", "assistant"}:
            logging.error(f"Invalid role in message: {message['role']}")
            return False
        if not isinstance(message["content"], str) or not message["content"].strip():
            logging.error(f"Message content must be a non-empty string: {message['content']}")
            return False

    return True


# ================================= Template Construction =================================

def construct_claude_developer_message(prompt: str) -> Dict[str, str]:
    """
    Construct a developer/system-style instruction for Claude.

    Since Claude does not support "system" messages natively, this function
    returns a structured user message that mimics system instructions.

    Args:
        prompt (str): The system prompt to guide Claude's behavior.

    Returns:
        Dict[str, str]: A dictionary with "role" as "user" and structured content.
    """
    return {"role": "user", "content": f"[System Instruction]: {prompt}"}


def construct_claude_user_message(content: str) -> Dict[str, str]:
    """
    Construct a user message for Claude conversations.
    """
    return {"role": "user", "content": content}


def construct_claude_assistant_message(content: str) -> Dict[str, str]:
    """
    Construct an assistant message for Claude conversations.
    """
    return {"role": "assistant", "content": content}


# ================================= Helper Functions =================================

def split_text_into_chunks(text: str, max_length: int = 4096) -> List[str]:
    """
    Split a long text into smaller chunks, ensuring each chunk does not exceed the max length.
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


def extract_xml_tags(text: str) -> Dict[str, str]:
    """
    Extract XML-style tags from Claude's response.
    Claude often uses XML-style tags to structure output.

    Args:
        text (str): The text containing XML tags.

    Returns:
        Dict[str, str]: A dictionary mapping tag names to their content.
    """
    tags = {}
    pattern = r"<([^>]+)>(.*?)</\1>"
    matches = re.finditer(pattern, text, re.DOTALL)
    for match in matches:
        tag_name = match.group(1)
        content = match.group(2).strip()
        tags[tag_name] = content
    return tags


# ================================= Logging and Reporting =================================

async def log_and_upload_to_s3(bucket: str, key: str, log_data: str) -> None:
    """
    Log data locally and upload it to S3.
    """
    try:
        logging.info(f"Log data: {log_data}")
        await async_upload_to_s3(bucket, key, log_data.encode('utf-8'), content_type="text/plain")
        logging.info(f"Log successfully uploaded to S3: s3://{bucket}/{key}")
    except Exception as e:
        logging.error(f"Error logging and uploading to S3: {e}")
