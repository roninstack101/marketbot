"""
Brand voice management tools.
These let the agent create, retrieve, list, and delete per-brand voice profiles.
"""
import json

import structlog

from app.brand.store import (
    get_brand_voice_data,
    list_all_brands,
    remove_brand_voice,
    upsert_brand_voice,
)

log = structlog.get_logger(__name__)


async def save_brand_voice(
    brand_name: str,
    display_name: str,
    tone: str,
    personality: str = "",
    target_audience: str = "",
    dos: list | str = "",
    donts: list | str = "",
    example_phrases: list | str = "",
    extra_notes: str = "",
) -> str:
    """
    Create or update a brand voice profile. Overwrites all fields on update.

    Args:
        brand_name:       Unique slug for the brand (e.g. "nike", "world-goods-market").
                          Automatically lowercased and hyphenated.
        display_name:     Human-friendly name shown in outputs (e.g. "Nike", "World Goods Market").
        tone:             Core tone description (e.g. "bold and inspirational").
        personality:      Brand personality traits (e.g. "energetic, inclusive, ambitious").
        target_audience:  Who the brand speaks to (e.g. "athletes aged 18-35").
        dos:              List (or comma-string) of writing rules to follow.
        donts:            List (or comma-string) of things to avoid.
        example_phrases:  Sample phrases or taglines that capture the voice.
        extra_notes:      Any additional brand guidelines.

    Returns:
        JSON confirmation with brand_name, display_name, and action (created/updated).
    """
    # Accept comma-separated strings as well as lists
    def _to_list(val: list | str) -> list:
        if isinstance(val, list):
            return [v.strip() for v in val if v.strip()]
        if isinstance(val, str) and val.strip():
            return [v.strip() for v in val.split(",") if v.strip()]
        return []

    log.info("save_brand_voice", brand=brand_name)
    result = await upsert_brand_voice(
        brand_name=brand_name,
        display_name=display_name,
        tone=tone,
        personality=personality,
        target_audience=target_audience,
        dos=_to_list(dos),
        donts=_to_list(donts),
        example_phrases=_to_list(example_phrases),
        extra_notes=extra_notes,
    )
    return json.dumps(result, indent=2)


async def get_brand_voice(brand_name: str) -> str:
    """
    Retrieve a brand voice profile by name.

    Args:
        brand_name: The brand slug (e.g. "nike") or display name.

    Returns:
        JSON with the full brand profile, or an error message if not found.
    """
    log.info("get_brand_voice", brand=brand_name)
    data = await get_brand_voice_data(brand_name)
    if not data:
        return json.dumps(
            {"status": "not_found", "brand_name": brand_name,
             "message": f"No brand voice saved for '{brand_name}'. Use save_brand_voice to create one."},
            indent=2,
        )
    return json.dumps({"status": "found", **data}, indent=2)


async def list_brand_voices() -> str:
    """
    List all saved brand voice profiles.

    Returns:
        JSON array with a summary of every brand (name, tone, audience, last updated).
    """
    log.info("list_brand_voices")
    brands = await list_all_brands()
    return json.dumps(
        {"count": len(brands), "brands": brands},
        indent=2,
    )


async def delete_brand_voice(brand_name: str) -> str:
    """
    Permanently delete a brand voice profile.  ⚠ REQUIRES APPROVAL

    Args:
        brand_name: The brand slug or display name to delete.

    Returns:
        JSON confirmation.
    """
    log.info("delete_brand_voice", brand=brand_name)
    deleted = await remove_brand_voice(brand_name)
    if deleted:
        return json.dumps(
            {"status": "deleted", "brand_name": brand_name},
            indent=2,
        )
    return json.dumps(
        {"status": "not_found", "brand_name": brand_name,
         "message": f"No brand voice found for '{brand_name}'."},
        indent=2,
    )
