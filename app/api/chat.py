"""
Chat endpoint – synchronous LLM conversation with user memory context.

POST /api/v1/chat
  Input:  {message, user_id}
  Output: {reply}

No Celery, no polling. For quick conversational responses.
Use the task pipeline (/tasks) for tool-based operations.
"""
import traceback

from pydantic import BaseModel, Field
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.agent.llm_client import call_llm
from app.config import get_settings
from app.logging_config import get_logger
from app.memory.user_store import format_user_memory_context

log = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])
settings = get_settings()

_SYSTEM = """\
You are ClaudBot, a helpful AI assistant for marketing, business, and general tasks.
Be concise, friendly, and direct.

For complex operations that require tools — writing full email campaigns, generating images,
building websites, researching live topics, writing long-form content, writing/debugging code —
let the user know they can send the request as a *task* by prefixing it with "task:" or using
the /task command in Telegram. Tasks run through a full agent with access to real tools.

For everything else — questions, advice, short answers, brainstorming, casual conversation —
respond directly and helpfully.
"""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_id: str = ""


class ChatResponse(BaseModel):
    reply: str


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    try:
        user_context = ""
        if payload.user_id:
            user_context = await format_user_memory_context(payload.user_id)

        system = _SYSTEM if not user_context else f"{_SYSTEM}\n\n{user_context}"

        fast_model = (
            settings.llm_model_fast_list[0]
            if settings.llm_model_fast_list
            else settings.llm_model
        )

        log.info("chat_request", model=fast_model, user_id=payload.user_id)

        reply = await call_llm(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": payload.message},
            ],
            model=fast_model,
            temperature=0.7,
            max_tokens=1024,
        )

        return ChatResponse(reply=reply)

    except Exception as exc:
        log.error("chat_error", error=str(exc), trace=traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )
