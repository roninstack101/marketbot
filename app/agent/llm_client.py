"""
Thin wrapper around litellm that adds:
  - Automatic retries with exponential back-off
  - Structured JSON parsing with validation
  - Consistent logging
"""
import json
import os
from contextvars import ContextVar
from typing import Any, Optional

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging_config import get_logger

# Set by the executor before each tool call via llm_router.
# Holds an ordered list: primary model first, fallbacks after.
# call_llm tries each in order on quota/rate-limit errors.
active_model: ContextVar[Optional[list[str]]] = ContextVar("active_model", default=None)

log = get_logger(__name__)
settings = get_settings()

# Wire API keys into the environment so litellm picks them up automatically
if settings.openrouter_api_key:
    os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
if settings.anthropic_api_key:
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
if settings.google_api_key:
    os.environ["GEMINI_API_KEY"] = settings.google_api_key
if settings.nvidia_nim_api_key:
    os.environ["NVIDIA_NIM_API_KEY"] = settings.nvidia_nim_api_key

# Silence litellm's verbose default logging
litellm.set_verbose = False


_FALLBACK_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    litellm.NotFoundError,
)

# Models that support extended thinking via extra_body
_THINKING_MODELS = {"z-ai/glm4.7"}


def _extra_body_for(model: str) -> dict | None:
    """Return extra_body kwargs for models that support thinking mode."""
    model_short = model.split("/")[-1]
    if model_short in _THINKING_MODELS:
        return {"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}}
    return None


async def call_llm(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    num_retries: int | None = None,
) -> str:
    """
    Call the LLM and return the raw text content of the first choice.
    Tries each model in the fallback chain on quota/rate-limit errors.
    Automatically enables thinking mode for supported models (e.g. GLM-4.7).
    """
    if model:
        models = [model]
    else:
        ctx = active_model.get()
        models = ctx if ctx else [settings.llm_model]

    last_error: Exception | None = None

    for attempt_model in models:
        try:
            log.debug("llm_call", model=attempt_model, message_count=len(messages))

            kwargs: dict = dict(
                model=attempt_model,
                messages=messages,
                temperature=temperature if temperature is not None else settings.llm_temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                num_retries=num_retries if num_retries is not None else settings.llm_max_retries,
            )

            extra = _extra_body_for(attempt_model)
            if extra:
                kwargs["extra_body"] = extra

            response = await litellm.acompletion(**kwargs)

            content = response.choices[0].message.content or ""
            log.debug("llm_response", model=attempt_model, tokens=response.usage.total_tokens if response.usage else None)
            return content

        except _FALLBACK_ERRORS as exc:
            log.warning("llm_fallback", model=attempt_model, error=str(exc))
            last_error = exc
            continue

    raise last_error or RuntimeError("No models available")


async def call_llm_json(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """
    Call the LLM and parse the result as JSON.
    Strips markdown code fences if the model wraps the response in them.
    """
    raw = await call_llm(messages, model=model, temperature=temperature)

    # Strip ```json ... ``` or ``` ... ``` wrappers if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        cleaned = "\n".join(inner)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error("llm_json_parse_failed", raw=raw[:500], error=str(exc))
        raise ValueError(f"LLM returned non-JSON response: {exc}") from exc
