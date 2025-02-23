from src.api.claude.service import generate_full_response as claude_generate

async def get_ai_response(messages, model="gpt"):
    if "claude" in model:
        return await claude_generate(messages)
    return await gpt_generate(messages)
