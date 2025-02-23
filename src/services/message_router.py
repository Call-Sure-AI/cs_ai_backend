from src.api.gpt.service import generate_full_response as gpt_response
from src.api.claude.service import generate_full_response as claude_response

async def route_message(model, messages):
    if model.startswith("claude"):
        return await claude_response(messages)
    return await gpt_response(messages)
