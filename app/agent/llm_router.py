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

    # ── General Q&A ─────────────────────────────────────────────────────────
    "write_answer":        "standard",

    # ── Human-in-the-loop (no LLM) ──────────────────────────────────────────
    "ask_user":            None,

    # ── Data / memory (no LLM) ──────────────────────────────────────────────
    "store_data":          None,
    "retrieve_data":       None,
    "delete_data":         None,
    "send_email":          None,
}

_ROUTER_SYSTEM = """\
You are an LLM routing agent. Pick the best tier AND quality level for the given tool call.

Tier definitions:
  strong   – Most capable. For: complex algorithms, multi-step debugging, architectural
             analysis, tasks needing deep reasoning chains (>500-token outputs).
  creative – Creative + reasoning balance. For: marketing copy, web pages, brand-aware
             long-form writing, persuasive content.
  standard – Reliable general-purpose. For: documents, summaries, simple code,
             explanations, medium-length structured output.
  fast     – Cheap and quick. For: content under ~200 words, social posts, simple
             reformatting, short factual answers.

Quality level (determines which model within the tier to start from):
  high   – Use the most capable model in the tier. For: complex, nuanced, long outputs.
  medium – Use a mid-tier model. For: moderate complexity, standard length.
  low    – Use the cheapest model in the tier. For: simple, short, or repetitive tasks.

Return ONLY a valid JSON object – no markdown fences, no explanation outside it:
{"tier": "<strong|creative|standard|fast>", "quality": "<high|medium|low>", "reason": "<one sentence>"}
"""


def _tier_to_models(tier: str, quality: str = "high") -> list[str]:
    """
    Resolve a tier + quality level to an ordered list of models.

    Models in the list are ordered best → cheapest. Quality controls the
    starting position so cheap tasks skip expensive models entirely:
      high   → start at index 0 (best model, full fallback chain)
      medium → start at midpoint (skip top models, use mid-range + cheaper)
      low    → start at last model (cheapest only)
    """
    tier_lists = {
        "strong":   settings.llm_model_strong_list or settings.llm_model_list,
        "creative": settings.llm_model_creative_list or settings.llm_model_list,
        "standard": settings.llm_model_list,
        "fast":     settings.llm_model_fast_list or settings.llm_model_list,
    }
    models = list(tier_lists.get(tier, settings.llm_model_list))

    # Ensure default model is always the final fallback
    if settings.llm_model not in models:
        models.append(settings.llm_model)

    if len(models) <= 1 or quality == "high":
        return models

    n = len(models)
    start = (n // 2) if quality == "medium" else (n - 1)
    return models[start:]


async def _ai_route(
    tool_name: str,
    tool_input: dict,
    task_description: str,
    default_tier: str,
) -> tuple[str, str]:
    """
    Ask a cheap routing LLM to pick the best tier AND quality level.
    Returns (tier, quality). Falls back to (default_tier, 'high') on any error.
    """
    from app.agent.llm_client import call_llm_json  # lazy import – avoids circular

    safe_input = {
        k: (str(v)[:150] + "…" if isinstance(v, str) and len(str(v)) > 150 else v)
        for k, v in tool_input.items()
        if k not in ("code", "html")
    }

    human = f"""\
Tool: {tool_name}
Default tier: {default_tier}
Inputs: {json.dumps(safe_input, ensure_ascii=False)[:500]}
Overall task: {task_description[:200] or 'not provided'}

Pick the best tier and quality level. Respond with JSON only.
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
        tier = result.get("tier", default_tier)
        quality = result.get("quality", "high")
        reason = result.get("reason", "")

        if tier not in ("strong", "creative", "standard", "fast"):
            log.warning("llm_router_invalid_tier", tier=tier, fallback=default_tier)
            tier = default_tier

        if quality not in ("high", "medium", "low"):
            quality = "high"

        log.info(
            "llm_router_decision_ai",
            tool=tool_name,
            default_tier=default_tier,
            chosen_tier=tier,
            quality=quality,
            reason=reason,
        )
        return tier, quality

    except Exception as exc:
        log.warning("llm_router_ai_failed", error=str(exc), fallback=default_tier)
        return default_tier, "high"


async def route_llm(
    tool_name: str,
    tool_input: dict,
    task_description: str = "",
) -> Optional[list[str]]:
    """
    Decide which LLM models to use for this tool call.

    Returns:
        Ordered list of model strings to try (primary first, fallbacks after),
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
        tier, quality = await _ai_route(tool_name, tool_input, task_description, default_tier)
    else:
        tier, quality = default_tier, "high"

    models = _tier_to_models(tier, quality)
    log.info(
        "llm_router_decision",
        tool=tool_name,
        tier=tier,
        quality=quality,
        primary=models[0],
        fallbacks=len(models) - 1,
    )
    return models
