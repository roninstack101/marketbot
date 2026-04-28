"""
Campaign generator tool.

Calls the LLM to produce structured marketing campaign copy:
subject line, preview text, body HTML, and a call-to-action.
"""
import json

import structlog

from app.agent.llm_client import call_llm_json

log = structlog.get_logger(__name__)

CAMPAIGN_SYSTEM = """\
You are an expert marketing copywriter. Generate a complete email campaign
based on the brief provided.

Return a JSON object with these fields:
{
  "subject":        "<email subject line – max 60 chars>",
  "preview_text":   "<preview/snippet text – max 100 chars>",
  "headline":       "<main headline inside the email>",
  "body":           "<full email body in plain text, 3-5 paragraphs>",
  "cta_text":       "<call-to-action button label>",
  "cta_url":        "<URL placeholder or actual URL>",
  "tone":           "<tone used: professional | friendly | urgent | etc.>"
}
"""


async def generate_campaign(
    product: str,
    goal: str,
    audience: str,
    tone: str = "professional",
    brand_name: str = "",
    extra_notes: str = "",
) -> str:
    """
    Generate a full marketing email campaign.

    Args:
        product:     Product or service being promoted.
        goal:        Campaign objective (e.g. "drive sign-ups", "announce sale").
        audience:    Target audience description.
        tone:        Desired tone (professional | friendly | urgent | playful).
        brand_name:  Brand slug to apply stored brand voice (e.g. "nike").
        extra_notes: Any additional context or constraints.

    Returns:
        JSON string with all campaign copy fields.
    """
    log.info("generate_campaign", product=product, goal=goal, tone=tone, brand=brand_name or "none")

    brand_block = ""
    if brand_name:
        from app.brand.store import get_brand_voice_prompt
        brand_block = await get_brand_voice_prompt(brand_name)

    system = (brand_block + "\n\n" + CAMPAIGN_SYSTEM) if brand_block else CAMPAIGN_SYSTEM

    human_prompt = f"""\
Product / Service: {product}
Goal: {goal}
Target Audience: {audience}
Tone: {tone}
Extra notes: {extra_notes or 'None'}

Generate the campaign now.
"""

    result = await call_llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": human_prompt},
        ],
        temperature=0.5,
    )

    log.info("campaign_generated", subject=result.get("subject", "")[:60])
    return json.dumps(result, indent=2)
