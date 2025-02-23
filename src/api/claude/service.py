from anthropic import AsyncAnthropic
from typing import AsyncGenerator, List
import asyncio
import logging
from src.config.settings import CLAUDE_API_KEY, DEFAULT_CLAUDE_MODEL
from src.api.claude.utils import (
    validate_claude_message_format,
    construct_claude_developer_message,
    construct_claude_user_message,
    construct_claude_assistant_message,
    log_and_upload_to_s3,
    split_text_into_chunks,
)

# Initialize Anthropic async client
async_client = AsyncAnthropic(api_key=CLAUDE_API_KEY)


async def stream_text_response(messages: List[dict], model: str = DEFAULT_CLAUDE_MODEL, temperature: float = 0.7) -> AsyncGenerator[str, None]:
    """
    Stream a conversational text response from Claude in real-time.
    
    Args:
        messages (List[dict]): The conversation history consisting of message objects.
            Each object should have a "role" ("user" or "assistant") and "content" (the message text).
        model (str): The Claude model to use for text generation. Defaults to DEFAULT_CLAUDE_MODEL.
        temperature (float): A value between 0 and 1 that controls the randomness of the response.
    
    Yields:
        str: A chunk of the response text streamed in real-time from Claude.
    """
    if not validate_claude_message_format(messages):
        raise ValueError("Invalid Claude message format.")
    
    try:
        async for chunk in async_client.messages.stream(
            model=model,
            messages=messages,
            temperature=temperature
        ):
            if chunk.delta.text:
                yield chunk.delta.text
    except Exception as e:
        logging.error(f"Error during Claude streaming: {e}")
        raise RuntimeError(f"Error during Claude streaming: {e}") from e


async def generate_full_response(messages: List[dict], model: str = DEFAULT_CLAUDE_MODEL, temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """
    Generate a complete conversational response from Claude in one API call.
    
    Args:
        messages (List[dict]): The conversation history consisting of message objects.
        model (str): The Claude model to use for text generation.
        temperature (float): Controls randomness in the response.
        max_tokens (int): The maximum number of tokens to generate (default: 4096).
    
    Returns:
        str: The full response text generated by Claude.
    """
    if not validate_claude_message_format(messages):
        raise ValueError("Invalid Claude message format.")
    
    try:
        response = await async_client.messages.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.content[0].text.strip()
    except Exception as e:
        logging.error(f"Error generating full Claude response: {e}")
        raise RuntimeError(f"Error generating full Claude response: {e}") from e


async def batch_generate_responses(batch_messages: List[List[dict]], model: str = DEFAULT_CLAUDE_MODEL, temperature: float = 0.7) -> List[str]:
    """
    Generate responses for multiple message batches using parallel requests.
    
    Args:
        batch_messages (List[List[dict]]): A list of message batches.
        model (str): The Claude model to use.
        temperature (float): Controls randomness in responses.
    
    Returns:
        List[str]: A list of generated responses for each batch.
    """
    try:
        tasks = [
            generate_full_response(messages, model, temperature)
            for messages in batch_messages
        ]
        return await asyncio.gather(*tasks)
    except Exception as e:
        logging.error(f"Error generating batch Claude responses: {e}")
        raise RuntimeError(f"Error generating batch Claude responses: {e}") from e