"""
Tool registry – maps tool names to async callables.
Add new tools here and they become available to the planner automatically.
"""
from app.tools.brand_voice import (
    delete_brand_voice,
    get_brand_voice,
    list_brand_voices,
    save_brand_voice,
)
from app.tools.campaign import generate_campaign
from app.tools.coder import debug_code, explain_code, write_code
from app.tools.document_reader import read_document
from app.tools.summariser import summarise, summarise_url
from app.tools.web_search import research_topic, web_search
from app.tools.content_writer import (
    write_blog_post,
    write_document,
    write_seo_content,
    write_social_post,
)
from app.tools.email_writer import send_email, write_email
from app.tools.image_gen import generate_image
from app.tools.storage import delete_data, retrieve_data, store_data
from app.tools.web_builder import build_website, create_landing_page

TOOL_REGISTRY = {
    # ── Brand voice ────────────────────────────────────────────────────────────
    "save_brand_voice": save_brand_voice,
    "get_brand_voice": get_brand_voice,
    "list_brand_voices": list_brand_voices,
    "delete_brand_voice": delete_brand_voice,          # requires approval

    # ── Marketing ──────────────────────────────────────────────────────────────
    "generate_campaign": generate_campaign,
    "write_email": write_email,
    "send_email": send_email,                  # requires approval

    # ── Content writing ────────────────────────────────────────────────────────
    "write_blog_post": write_blog_post,
    "write_social_post": write_social_post,
    "write_document": write_document,
    "write_seo_content": write_seo_content,

    # ── Coding ─────────────────────────────────────────────────────────────────
    "write_code": write_code,
    "debug_code": debug_code,
    "explain_code": explain_code,

    # ── Web building ───────────────────────────────────────────────────────────
    "build_website": build_website,
    "create_landing_page": create_landing_page,

    # ── Image generation ───────────────────────────────────────────────────────
    "generate_image": generate_image,

    # ── Web search & research ──────────────────────────────────────────────────
    "web_search": web_search,
    "research_topic": research_topic,

    # ── Document reader ────────────────────────────────────────────────────────
    "read_document": read_document,

    # ── Summariser ─────────────────────────────────────────────────────────────
    "summarise": summarise,
    "summarise_url": summarise_url,

    # ── Data / memory ──────────────────────────────────────────────────────────
    "store_data": store_data,
    "retrieve_data": retrieve_data,
    "delete_data": delete_data,                # requires approval
}

__all__ = ["TOOL_REGISTRY"]
