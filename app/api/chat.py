"""
Chat endpoint – synchronous LLM conversation with user memory context.

POST /api/v1/chat
  Input:  {message, user_id}
  Output: {reply}

No Celery, no polling. For quick conversational responses.
Use the task pipeline (/tasks) for tool-based operations.
"""
import traceback

import litellm
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

        # Merge system prompt + user context into the user message so it works
        # with models that don't support the system role (e.g. Gemma via Google AI Studio).
        system = _SYSTEM if not user_context else f"{_SYSTEM}\n\n{user_context}"
        full_message = f"{system}\n\n---\nUser: {payload.message}"

        # Build fallback chain: fast tier → standard model as final fallback
        fast_models = settings.llm_model_fast_list or settings.llm_model_list
        if settings.llm_model not in fast_models:
            fast_models = list(fast_models) + [settings.llm_model]

        log.info("chat_request", models=fast_models, user_id=payload.user_id)

        token = active_model.set(fast_models)
        try:
            reply = await call_llm(
                messages=[{"role": "user", "content": full_message}],
                temperature=0.7,
                max_tokens=1024,
            )
        finally:
            active_model.reset(token)

        return ChatResponse(reply=reply)

    except Exception as exc:
        log.error("chat_error", error=str(exc), trace=traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )
