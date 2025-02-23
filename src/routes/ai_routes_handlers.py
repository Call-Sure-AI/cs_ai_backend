from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from models.schemas import ChatMessage
from src.api.gpt.service import generate_full_response as gpt_generate
from src.api.claude.service import generate_full_response as claude_generate

airouter = APIRouter()

@ai_router.post("/chat",
    response_model=Dict[str, Any],
    summary="Chat with AI"
)
async def chat(message: ChatMessage, model: str = "gpt"):
    try:
        if "claude" in model.lower():
            response = await claude_generate(message.messages)
        else:
            response = await gpt_generate(message.messages)
        
        return {"response": response, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
