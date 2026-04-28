"""
Brand voice store – async DB operations and the prompt-injection helper.
"""
import re
from typing import Any

import structlog
from sqlalchemy import delete, select

from app.database import get_async_db
from app.models.task import BrandVoice

log = structlog.get_logger(__name__)


def _slugify(name: str) -> str:
    """'World Goods Market' → 'world-goods-market'"""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


async def get_brand_voice_data(brand_name: str) -> dict[str, Any] | None:
    """Return a brand voice record as a plain dict, or None if not found."""
    slug = _slugify(brand_name)
    async with get_async_db() as session:
        row = (
            await session.execute(
                select(BrandVoice).where(BrandVoice.brand_name == slug)
            )
        ).scalar_one_or_none()

    if not row:
        return None

    return {
        "brand_name": row.brand_name,
        "display_name": row.display_name,
        "tone": row.tone,
        "personality": row.personality,
        "target_audience": row.target_audience,
        "dos": row.dos or [],
        "donts": row.donts or [],
        "example_phrases": row.example_phrases or [],
        "extra_notes": row.extra_notes,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def get_brand_voice_prompt(brand_name: str) -> str:
    """
    Returns a formatted brand voice block for injection into LLM system prompts.
    Returns an empty string if the brand is not found (tools handle this gracefully).
    """
    brand = await get_brand_voice_data(brand_name)
    if not brand:
        log.warning("brand_voice_not_found", brand_name=brand_name)
        return ""

    lines = [
        f"## Brand Voice: {brand['display_name']}",
        f"**Tone:** {brand['tone']}",
    ]
    if brand.get("personality"):
        lines.append(f"**Personality:** {brand['personality']}")
    if brand.get("target_audience"):
        lines.append(f"**Target Audience:** {brand['target_audience']}")
    if brand.get("dos"):
        lines.append("**Always do:** " + " | ".join(brand["dos"]))
    if brand.get("donts"):
        lines.append("**Never do:** " + " | ".join(brand["donts"]))
    if brand.get("example_phrases"):
        lines.append("**Example phrases:** " + " | ".join(brand["example_phrases"]))
    if brand.get("extra_notes"):
        lines.append(f"**Extra notes:** {brand['extra_notes']}")
    lines.append("\nApply this brand voice to ALL content you generate. Do not deviate.\n")

    return "\n".join(lines)


async def upsert_brand_voice(
    brand_name: str,
    display_name: str,
    tone: str,
    personality: str = "",
    target_audience: str = "",
    dos: list | None = None,
    donts: list | None = None,
    example_phrases: list | None = None,
    extra_notes: str = "",
) -> dict[str, Any]:
    """Create or fully replace a brand voice profile."""
    slug = _slugify(brand_name)

    async with get_async_db() as session:
        existing = (
            await session.execute(
                select(BrandVoice).where(BrandVoice.brand_name == slug)
            )
        ).scalar_one_or_none()

        if existing:
            existing.display_name = display_name
            existing.tone = tone
            existing.personality = personality or None
            existing.target_audience = target_audience or None
            existing.dos = dos or []
            existing.donts = donts or []
            existing.example_phrases = example_phrases or []
            existing.extra_notes = extra_notes or None
            record = existing
            action = "updated"
        else:
            record = BrandVoice(
                brand_name=slug,
                display_name=display_name,
                tone=tone,
                personality=personality or None,
                target_audience=target_audience or None,
                dos=dos or [],
                donts=donts or [],
                example_phrases=example_phrases or [],
                extra_notes=extra_notes or None,
            )
            session.add(record)
            action = "created"

    log.info("brand_voice_upserted", brand=slug, action=action)
    return {"brand_name": slug, "display_name": display_name, "action": action}


async def list_all_brands() -> list[dict[str, Any]]:
    """Return a summary list of all stored brand voices."""
    async with get_async_db() as session:
        rows = (
            await session.execute(
                select(BrandVoice).order_by(BrandVoice.display_name)
            )
        ).scalars().all()

    return [
        {
            "brand_name": r.brand_name,
            "display_name": r.display_name,
            "tone": r.tone,
            "target_audience": r.target_audience,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


async def remove_brand_voice(brand_name: str) -> bool:
    """Delete a brand voice by slug. Returns True if deleted, False if not found."""
    slug = _slugify(brand_name)
    async with get_async_db() as session:
        result = await session.execute(
            delete(BrandVoice).where(BrandVoice.brand_name == slug)
        )
    deleted = result.rowcount > 0
    log.info("brand_voice_deleted", brand=slug, found=deleted)
    return deleted
