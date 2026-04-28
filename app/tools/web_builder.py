"""
Website and web-page generation tools.
The LLM produces complete, self-contained HTML/CSS/JS files.
"""
import base64
import json
import os
import re
from pathlib import Path

import structlog

from app.agent.llm_client import call_llm

log = structlog.get_logger(__name__)

_OUTPUT_DIR = Path(os.getenv("WEB_OUTPUT_DIR", "./output/websites"))

_BUILD_WEBSITE_SYSTEM = """\
You are a senior full-stack web developer and designer.
Generate a complete, modern, responsive website as a SINGLE self-contained HTML file.

Requirements:
- All CSS must be in a <style> block in <head>.
- All JavaScript must be in a <script> block before </body>.
- No external dependencies – inline everything (use system fonts or Google Fonts CDN only).
- Mobile-first, fully responsive layout.
- Semantic HTML5 elements (header, nav, main, section, footer, etc.).
- Smooth scroll, subtle hover transitions, professional look.
- Include a navigation bar linking to each section.
- Real, meaningful placeholder content that fits the site purpose.

Return ONLY the raw HTML – no markdown fences, no explanations before or after.
"""

_LANDING_PAGE_SYSTEM = """\
You are an expert conversion-focused web designer.
Generate a high-converting landing page as a SINGLE self-contained HTML file.

Requirements:
- All CSS inside <style> in <head>.
- All JS inside <script> before </body>.
- No external CDN except Google Fonts.
- Sections: hero (with CTA button), features/benefits, social proof, final CTA.
- Mobile-responsive, fast-loading.
- Bold, attention-grabbing headline. Clear value proposition.

Return ONLY the raw HTML – no markdown, no explanations.
"""


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _extract_image_data_uris(image_paths_raw: str) -> list[str]:
    """
    Parse generate_image JSON output(s) or comma-separated file paths into
    base64 data URIs ready to embed in HTML.
    """
    if not image_paths_raw:
        return []

    paths: list[str] = []
    # Try JSON first (single generate_image output or a list)
    stripped = image_paths_raw.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                parsed = [parsed]
            for item in parsed:
                fp = item.get("file_path") or item.get("path", "")
                if fp:
                    paths.append(fp)
        except (json.JSONDecodeError, AttributeError):
            pass

    if not paths:
        paths = [p.strip() for p in image_paths_raw.split(",") if p.strip()]

    data_uris: list[str] = []
    for p in paths:
        try:
            raw = Path(p).read_bytes()
            ext = Path(p).suffix.lstrip(".").lower() or "png"
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            data_uris.append(f"data:{mime};base64,{base64.b64encode(raw).decode()}")
        except OSError:
            pass

    return data_uris


def _save_html(subfolder: str, filename: str, html: str) -> str:
    out_dir = _OUTPUT_DIR / subfolder
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(html, encoding="utf-8")
    return str(path)


async def build_website(
    title: str,
    description: str,
    sections: list | str,
    style: str = "modern minimalist",
    color_scheme: str = "blue and white",
    brand_name: str = "",
    reference_content: str = "",
    image_paths: str = "",
    extra_notes: str = "",
) -> str:
    """
    Generate a complete multi-section website as a single HTML file.

    Args:
        title:        Site/business name shown in navbar and title tag.
        description:  What the site is about (purpose, niche, tone).
        sections:     List of page sections (e.g. ["hero","about","services","contact"])
                      or a comma-separated string.
        style:        Visual style (modern minimalist | corporate | bold creative | etc.).
        color_scheme: Primary colors (e.g. "dark navy and gold").
        brand_name:        Brand slug to apply stored brand voice (e.g. "nike").
        reference_content: Text extracted from a reference site (output of summarise_url).
        image_paths:       JSON from generate_image steps or comma-separated file paths.
        extra_notes:       Any additional design or content requirements.

    Returns:
        JSON string with the saved file path and a summary.
    """
    if isinstance(sections, str):
        sections = [s.strip() for s in sections.split(",")]

    log.info("build_website", title=title, sections=sections, brand=brand_name or "none")

    brand_block = ""
    if brand_name:
        from app.brand.store import get_brand_voice_prompt
        brand_block = await get_brand_voice_prompt(brand_name)

    system = (brand_block + "\n\n" + _BUILD_WEBSITE_SYSTEM) if brand_block else _BUILD_WEBSITE_SYSTEM

    reference_block = (
        f"\n\n## Reference site (use for structure/content inspiration — do not copy verbatim)\n{reference_content[:3000]}"
        if reference_content else ""
    )

    data_uris = _extract_image_data_uris(image_paths)
    image_block = ""
    if data_uris:
        tags = "\n".join(f'<img src="{uri}" alt="site image {i+1}">' for i, uri in enumerate(data_uris))
        image_block = f"\n\n## Generated images — embed these exactly as-is in appropriate sections:\n{tags}"

    human = f"""\
Site title: {title}
Description: {description}
Sections (in order): {', '.join(sections)}
Visual style: {style}
Color scheme: {color_scheme}
Extra notes: {extra_notes or 'None'}{reference_block}{image_block}

Build the complete website HTML now.
"""
    html = await call_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": human},
        ],
        temperature=0.4,
        max_tokens=8192,
    )

    slug = _slugify(title)
    path = _save_html(slug, "index.html", html)
    log.info("website_built", path=path, html_bytes=len(html))

    return json.dumps(
        {
            "status": "success",
            "file_path": path,
            "title": title,
            "sections": sections,
            "html_size_bytes": len(html),
            "summary": f"Complete website for '{title}' saved to {path}",
        },
        indent=2,
    )


async def create_landing_page(
    product_name: str,
    headline: str,
    value_proposition: str,
    cta_text: str = "Get Started",
    cta_url: str = "#",
    features: list | str = "",
    style: str = "modern",
    brand_name: str = "",
    reference_content: str = "",
    image_paths: str = "",
    extra_notes: str = "",
) -> str:
    """
    Generate a conversion-optimised landing page as a single HTML file.

    Args:
        product_name:       Name of the product or service.
        headline:           Bold hero headline.
        value_proposition:  What makes the product unique/valuable.
        cta_text:           Call-to-action button label.
        cta_url:            CTA button link target.
        features:           List (or comma-string) of key features/benefits.
        style:              Visual style (modern | bold | minimal | saas).
        extra_notes:        Additional requirements.

    Returns:
        JSON string with the saved file path and a summary.
    """
    if isinstance(features, str) and features:
        features = [f.strip() for f in features.split(",")]
    elif not features:
        features = []

    log.info("create_landing_page", product=product_name, brand=brand_name or "none")

    brand_block = ""
    if brand_name:
        from app.brand.store import get_brand_voice_prompt
        brand_block = await get_brand_voice_prompt(brand_name)

    system = (brand_block + "\n\n" + _LANDING_PAGE_SYSTEM) if brand_block else _LANDING_PAGE_SYSTEM

    reference_block = (
        f"\n\n## Reference site (use for structure/content inspiration — do not copy verbatim)\n{reference_content[:3000]}"
        if reference_content else ""
    )

    data_uris = _extract_image_data_uris(image_paths)
    image_block = ""
    if data_uris:
        tags = "\n".join(f'<img src="{uri}" alt="product image {i+1}">' for i, uri in enumerate(data_uris))
        image_block = f"\n\n## Generated images — embed these exactly as-is in appropriate sections:\n{tags}"

    human = f"""\
Product name: {product_name}
Hero headline: {headline}
Value proposition: {value_proposition}
CTA button text: {cta_text}
CTA URL: {cta_url}
Key features / benefits: {', '.join(features) if features else 'Generate 3 compelling features'}
Visual style: {style}
Extra notes: {extra_notes or 'None'}{reference_block}{image_block}

Generate the high-converting landing page HTML now.
"""
    html = await call_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": human},
        ],
        temperature=0.4,
        max_tokens=8192,
    )

    slug = _slugify(product_name)
    path = _save_html(f"{slug}-landing", "index.html", html)
    log.info("landing_page_created", path=path)

    return json.dumps(
        {
            "status": "success",
            "file_path": path,
            "product_name": product_name,
            "headline": headline,
            "html_size_bytes": len(html),
            "summary": f"Landing page for '{product_name}' saved to {path}",
        },
        indent=2,
    )
