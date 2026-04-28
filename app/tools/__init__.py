"""
Tool registry – maps tool names to async callables.
Add new tools here and they become available to the planner automatically.
"""
from app.tools.campaign import generate_campaign
from app.tools.coder import debug_code, explain_code, write_code
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

    # ── Data / memory ──────────────────────────────────────────────────────────
    "store_data": store_data,
    "retrieve_data": retrieve_data,
    "delete_data": delete_data,                # requires approval
}

__all__ = ["TOOL_REGISTRY"]
