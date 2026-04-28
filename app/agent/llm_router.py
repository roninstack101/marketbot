"""
LLM Router – decides which model to use for each tool call.

Two modes:
  1. Static (always on): a tier table maps each tool to strong/creative/standard/fast.
  2. AI-assisted (opt-in, LLM_ROUTER_ENABLED=true): a cheap routing LLM analyses
     the actual inputs and can upgrade or downgrade the tier based on complexity.

Tier → model mapping is controlled by four .env keys:
  LLM_MODEL_STRONG    – best reasoning  (e.g. claude-opus-4, gpt-4o)
  LLM_MODEL_CREATIVE  – creative tasks  (e.g. claude-sonnet-4, gpt-4o)
  LLM_MODEL_FAST      – cheap & quick   (e.g. gemini-flash, gpt-4o-mini, claude-haiku)
  LLM_MODEL           – standard / default fallback

Any unset tier falls back to LLM_MODEL so the bot works with a single key out of the box.
"""
import json
from contextvars import ContextVar
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Active-model context variable ────────────────────────────────────────────
# The executor sets this before calling a tool; call_llm reads it automatically.
# Using ContextVar makes this async-safe (each coroutine has its own value).
active_model: ContextVar[Optional[str]] = ContextVar("active_model", default=None)

# ── Tool → default tier ───────────────────────────────────────────────────────
# strong   : best reasoning model  – complex code, deep analysis
# creative : creative + reasoning  – marketing copy, web content, long writing
# standard : reliable default      – documents, explanations, moderate content
# fast     : cheap & quick         – short posts, simple lookups, reformatting
# None     : tool uses no LLM      – skip routing entirely

TOOL_TIERS: dict[str, Optional[str]] = {
    # ── Coding ──────────────────────────────────────────────────────────────
    "write_code":          "strong",
    "debug_code":          "strong",
    "explain_code":        "standard",

    # ── Marketing ───────────────────────────────────────────────────────────
    "generate_campaign":   "creative",
    "write_email":         "creative",

    # ── Content writing ─────────────────────────────────────────────────────
    "write_blog_post":     "creative",
    "write_social_post":   "fast",
    "write_document":      "standard",
    "write_seo_content":   "standard",

    # ── Web building ────────────────────────────────────────────────────────
    "build_website":       "creative",
    "create_landing_page": "creative",

    # ── Research & search ────────────────────────────────────────────────────
    "web_search":          None,       # pure API call, no LLM
    "research_topic":      "strong",   # synthesis requires good reasoning
    "read_document":       None,       # pure parsing, no LLM
    "summarise":           "fast",     # AI router may upgrade for long/complex docs
    "summarise_url":       "fast",

    # ── Brand voice ─────────────────────────────────────────────────────────
    "save_brand_voice":    "fast",
    "get_brand_voice":     None,
    "list_brand_voices":   None,
    "delete_brand_voice":  None,

    # ── Image (calls OpenAI directly, not routed) ───────────────────────────
    "generate_image":      None,

    # ── Human-in-the-loop (no LLM) ──────────────────────────────────────────
    "ask_user":            None,

    # ── Data / memory (no LLM) ──────────────────────────────────────────────
    "store_data":          None,
    "retrieve_data":       None,
    "delete_data":         None,
    "send_email":          None,
}

_ROUTER_SYSTEM = """\
You are an LLM routing agent. Pick the best performance tier for the given tool call.

Tier definitions:
  strong   – Most capable and expensive. For: complex algorithms, multi-step debugging,
             architectural analysis, tasks needing deep reasoning chains (>500-token outputs).
  creative – Creative + reasoning balance. For: marketing copy, web pages, brand-aware
             long-form writing, persuasive content.
  standard – Reliable general-purpose. For: documents, summaries, simple code,
             explanations, medium-length structured output.
  fast     – Cheap and quick. For: content under ~200 words, social posts, simple
             reformatting, short factual answers.

Return ONLY a valid JSON object – no markdown fences, no explanation outside it:
{"tier": "<strong|creative|standard|fast>", "reason": "<one sentence>"}
"""


def _tier_to_model(tier: str) -> str:
    """Resolve a tier name to the configured model string."""
    return {
        "strong":   settings.llm_model_strong   or settings.llm_model,
        "creative": settings.llm_model_creative  or settings.llm_model,
        "standard": settings.llm_model,
        "fast":     settings.llm_model_fast      or settings.llm_model,
    }.get(tier, settings.llm_model)


async def _ai_route(
    tool_name: str,
    tool_input: dict,
    task_description: str,
    default_tier: str,
) -> str:
    """
    Ask a cheap routing LLM whether to change the default tier.
    Falls back to the default tier on any error.
    """
    from app.agent.llm_client import call_llm_json  # lazy import – avoids circular

    # Truncate large values so the routing call stays cheap
    safe_input = {
        k: (str(v)[:150] + "…" if isinstance(v, str) and len(str(v)) > 150 else v)
        for k, v in tool_input.items()
        if k not in ("code", "html")       # skip raw code/html blobs
    }

    human = f"""\
Tool: {tool_name}
Default tier: {default_tier}
Inputs: {json.dumps(safe_input, ensure_ascii=False)[:500]}
Overall task: {task_description[:200] or 'not provided'}

Should the tier stay as '{default_tier}' or change? Respond with JSON only.
"""
    router_model = (
        settings.llm_router_model
        or settings.llm_model_fast
        or settings.llm_model
    )

    try:
        result = await call_llm_json(
            [
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": human},
            ],
            model=router_model,
            temperature=0.0,
        )
        chosen = result.get("tier", default_tier)
        reason = result.get("reason", "")

        if chosen not in ("strong", "creative", "standard", "fast"):
            log.warning("llm_router_invalid_tier", chosen=chosen, fallback=default_tier)
            return default_tier

        if chosen != default_tier:
            log.info(
                "llm_router_override",
                tool=tool_name,
                default=default_tier,
                chosen=chosen,
                reason=reason,
            )
        return chosen

    except Exception as exc:
        log.warning("llm_router_ai_failed", error=str(exc), fallback=default_tier)
        return default_tier


async def route_llm(
    tool_name: str,
    tool_input: dict,
    task_description: str = "",
) -> Optional[str]:
    """
    Decide which LLM model to use for this tool call.

    Returns:
        Model string (e.g. 'openrouter/anthropic/claude-opus-4'),
        or None if the tool doesn't use an LLM (caller should skip setting context).
    """
    default_tier = TOOL_TIERS.get(tool_name)

    if default_tier is None:
        log.debug("llm_router_skip", tool=tool_name)
        return None

    # AI routing only fires when explicitly enabled AND multiple tiers are configured
    multiple_tiers_configured = bool(
        settings.llm_model_strong or settings.llm_model_creative or settings.llm_model_fast
    )
    if settings.llm_router_enabled and multiple_tiers_configured:
        tier = await _ai_route(tool_name, tool_input, task_description, default_tier)
    else:
        tier = default_tier

    model = _tier_to_model(tier)
    log.info("llm_router_decision", tool=tool_name, tier=tier, model=model)
    return model
