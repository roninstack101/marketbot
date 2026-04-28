"""
Image generation tool using OpenAI DALL-E 3.
Falls back to a descriptive prompt analysis if the API key is not configured.
"""
import json
import os
import uuid
from pathlib import Path

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

_OUTPUT_DIR = Path(os.getenv("IMAGE_OUTPUT_DIR", "./output/images"))

_VALID_SIZES = {"1024x1024", "1792x1024", "1024x1792"}
_VALID_STYLES = {"vivid", "natural"}
_VALID_QUALITY = {"standard", "hd"}


async def _download_image(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)


async def generate_image(
    prompt: str,
    size: str = "1024x1024",
    style: str = "vivid",
    quality: str = "standard",
    save_to_disk: bool = True,
) -> str:
    """
    Generate an image using OpenAI DALL-E 3 from a text prompt.

    Args:
        prompt:       Detailed description of the image to generate.
        size:         Image dimensions – '1024x1024' | '1792x1024' | '1024x1792'.
        style:        'vivid' (hyper-real) or 'natural' (more subdued).
        quality:      'standard' or 'hd' (higher detail, slower, costs more).
        save_to_disk: Whether to download and save the image locally.

    Returns:
        JSON string with the image URL, local path (if saved), and revised prompt.
    """
    settings = get_settings()
    openai_key = settings.openai_api_key

    if size not in _VALID_SIZES:
        size = "1024x1024"
    if style not in _VALID_STYLES:
        style = "vivid"
    if quality not in _VALID_QUALITY:
        quality = "standard"

    log.info("generate_image", size=size, style=style, quality=quality)

    if not openai_key:
        log.warning("generate_image_no_key", msg="OPENAI_API_KEY not configured")
        return json.dumps(
            {
                "status": "error",
                "error": "OPENAI_API_KEY is not configured. Add it to your .env file to enable image generation.",
                "prompt": prompt,
            },
            indent=2,
        )

    # Call OpenAI Images API directly via httpx (no extra SDK needed)
    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "style": style,
        "quality": quality,
        "response_format": "url",
    }

    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    image_url: str = data["data"][0]["url"]
    revised_prompt: str = data["data"][0].get("revised_prompt", prompt)

    local_path: str | None = None
    if save_to_disk:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        dest = _OUTPUT_DIR / filename
        try:
            await _download_image(image_url, dest)
            local_path = str(dest)
            log.info("image_saved", path=local_path)
        except Exception as exc:
            log.warning("image_save_failed", error=str(exc))

    log.info("image_generated", url=image_url[:60])
    return json.dumps(
        {
            "status": "success",
            "image_url": image_url,
            "local_path": local_path,
            "revised_prompt": revised_prompt,
            "size": size,
            "style": style,
            "quality": quality,
            "note": "DALL-E image URLs expire after ~60 minutes. Use local_path for permanent storage.",
        },
        indent=2,
    )
