"""
Content writing tools – blog posts, social media, documents, and SEO copy.
All tools accept an optional brand_name that auto-injects the stored brand voice.
"""
import json

import structlog

from app.agent.llm_client import call_llm_json

log = structlog.get_logger(__name__)

_BLOG_SYSTEM = """\
You are a world-class content writer and SEO expert.
Write a complete, engaging blog post based on the brief.

Return a JSON object:
{
  "title": "<SEO-friendly title>",
  "meta_description": "<155-char meta description>",
  "word_count": <actual word count>,
  "content": "<full blog post in Markdown format with headings, paragraphs, and a conclusion>",
  "key_takeaways": ["<bullet-point takeaways>"],
  "suggested_tags": ["<relevant tags/categories>"]
}

Do NOT wrap in markdown fences.
"""

_SOCIAL_SYSTEM = """\
You are a social media expert who writes high-engagement posts.

Return a JSON object:
{
  "platform": "<platform name>",
  "post": "<the post text, formatted for the platform>",
  "hashtags": ["<relevant hashtags without #>"],
  "character_count": <character count of post>,
  "best_time_to_post": "<recommended posting time e.g. Tuesday 10am>",
  "engagement_tip": "<one actionable tip to maximise engagement>"
}

Platform limits: Twitter/X ≤ 280 chars, LinkedIn ≤ 3000, Instagram caption ≤ 2200, Facebook ≤ 63206.
Do NOT wrap in markdown fences.
"""

_DOCUMENT_SYSTEM = """\
You are an expert business writer. Produce a professional document based on the brief.

Return a JSON object:
{
  "document_type": "<type of document>",
  "title": "<document title>",
  "content": "<full document content in Markdown, with proper headings and structure>",
  "word_count": <word count>,
  "summary": "<2-sentence executive summary>"
}

Do NOT wrap in markdown fences.
"""

_SEO_SYSTEM = """\
You are an SEO specialist and content strategist.
Write optimised web copy that ranks for the target keyword while reading naturally.

Return a JSON object:
{
  "page_title": "<SEO page title ≤ 60 chars>",
  "meta_description": "<meta description ≤ 155 chars>",
  "h1": "<main heading with primary keyword>",
  "content": "<full SEO-optimised page content in Markdown; include H2/H3 subheadings, keyword variations, and internal-link suggestions in [brackets]>",
  "word_count": <word count>,
  "keyword_density": "<approximate % for primary keyword>",
  "internal_link_suggestions": ["<suggested anchor texts>"],
  "schema_type": "<recommended schema markup type>"
}

Do NOT wrap in markdown fences.
"""


async def _brand_prefix(brand_name: str) -> str:
    if not brand_name:
        return ""
    from app.brand.store import get_brand_voice_prompt
    return await get_brand_voice_prompt(brand_name)


async def write_blog_post(
    topic: str,
    audience: str,
    word_count: int = 800,
    tone: str = "informative and engaging",
    keywords: str = "",
    brand_name: str = "",
    extra_notes: str = "",
) -> str:
    """
    Write a complete, publish-ready blog post.

    Args:
        topic:       Blog post topic or working title.
        audience:    Target reader (e.g. "small business owners", "developers").
        word_count:  Approximate desired word count (default 800).
        tone:        Writing tone (informative | conversational | authoritative | etc.).
        keywords:    Comma-separated SEO keywords to weave in naturally.
        brand_name:  Brand slug to apply stored brand voice (e.g. "nike"). Leave blank for no brand.
        extra_notes: Any additional style or content requirements.

    Returns:
        JSON string with title, meta description, full Markdown content, and tags.
    """
    log.info("write_blog_post", topic=topic[:80], word_count=word_count, brand=brand_name or "none")

    brand_block = await _brand_prefix(brand_name)
    system = (brand_block + "\n\n" + _BLOG_SYSTEM) if brand_block else _BLOG_SYSTEM

    human = f"""\
Topic: {topic}
Target audience: {audience}
Desired word count: ~{word_count} words
Tone: {tone}
SEO keywords to include: {keywords or 'None specified'}
Extra notes: {extra_notes or 'None'}

Write the full blog post now.
"""
    result = await call_llm_json(
        [{"role": "system", "content": system}, {"role": "user", "content": human}],
        temperature=0.6,
    )
    log.info("blog_post_written", title=result.get("title", "")[:60])
    return json.dumps(result, indent=2)


async def write_social_post(
    platform: str,
    topic: str,
    tone: str = "engaging",
    include_hashtags: bool = True,
    brand_name: str = "",
    brand_voice: str = "",
    extra_notes: str = "",
) -> str:
    """
    Write a platform-optimised social media post.

    Args:
        platform:         Target platform: twitter | linkedin | instagram | facebook | tiktok.
        topic:            What the post is about.
        tone:             Tone: engaging | professional | humorous | inspiring | urgent.
        include_hashtags: Whether to generate relevant hashtags.
        brand_name:       Brand slug to apply stored brand voice (e.g. "nike").
        brand_voice:      Inline brand voice notes (used if brand_name is not set).
        extra_notes:      Additional requirements.

    Returns:
        JSON string with post text, hashtags, character count, and engagement tips.
    """
    log.info("write_social_post", platform=platform, topic=topic[:60], brand=brand_name or "none")

    brand_block = await _brand_prefix(brand_name)
    system = (brand_block + "\n\n" + _SOCIAL_SYSTEM) if brand_block else _SOCIAL_SYSTEM

    human = f"""\
Platform: {platform}
Topic: {topic}
Tone: {tone}
Include hashtags: {include_hashtags}
Brand voice notes: {brand_voice or 'Not specified – use a professional, friendly voice'}
Extra notes: {extra_notes or 'None'}

Write the social media post now.
"""
    result = await call_llm_json(
        [{"role": "system", "content": system}, {"role": "user", "content": human}],
        temperature=0.7,
    )
    log.info("social_post_written", platform=platform)
    return json.dumps(result, indent=2)


async def write_document(
    doc_type: str,
    topic: str,
    context: str = "",
    word_count: int = 500,
    tone: str = "professional",
    brand_name: str = "",
    extra_notes: str = "",
) -> str:
    """
    Write a professional business document of any type.

    Args:
        doc_type:    Type: report | proposal | cover_letter | press_release |
                     job_description | meeting_agenda | policy | faq | terms | other.
        topic:       Subject matter or title of the document.
        context:     Background information or key points to include.
        word_count:  Approximate target length.
        tone:        Writing tone (professional | formal | friendly | persuasive).
        brand_name:  Brand slug to apply stored brand voice.
        extra_notes: Additional requirements.

    Returns:
        JSON string with document title, full Markdown content, and executive summary.
    """
    log.info("write_document", doc_type=doc_type, topic=topic[:80], brand=brand_name or "none")

    brand_block = await _brand_prefix(brand_name)
    system = (brand_block + "\n\n" + _DOCUMENT_SYSTEM) if brand_block else _DOCUMENT_SYSTEM

    human = f"""\
Document type: {doc_type}
Topic / Title: {topic}
Background context: {context or 'None provided'}
Target word count: ~{word_count} words
Tone: {tone}
Extra notes: {extra_notes or 'None'}

Write the complete document now.
"""
    result = await call_llm_json(
        [{"role": "system", "content": system}, {"role": "user", "content": human}],
        temperature=0.4,
    )
    log.info("document_written", title=result.get("title", "")[:60])
    return json.dumps(result, indent=2)


async def write_seo_content(
    target_keyword: str,
    page_purpose: str,
    secondary_keywords: str = "",
    word_count: int = 1000,
    audience: str = "",
    brand_name: str = "",
    extra_notes: str = "",
) -> str:
    """
    Write SEO-optimised web page copy targeting a specific keyword.

    Args:
        target_keyword:     Primary keyword to rank for.
        page_purpose:       What the page is for (e.g. "service page for a plumber in London").
        secondary_keywords: Comma-separated related keywords / LSI terms.
        word_count:         Approximate target word count.
        audience:           Target reader persona.
        brand_name:         Brand slug to apply stored brand voice.
        extra_notes:        Any CRO or formatting requirements.

    Returns:
        JSON string with page title, meta description, H1, full Markdown content,
        keyword density, and internal link suggestions.
    """
    log.info("write_seo_content", keyword=target_keyword, brand=brand_name or "none")

    brand_block = await _brand_prefix(brand_name)
    system = (brand_block + "\n\n" + _SEO_SYSTEM) if brand_block else _SEO_SYSTEM

    human = f"""\
Primary keyword: {target_keyword}
Page purpose: {page_purpose}
Secondary keywords / LSI: {secondary_keywords or 'None – generate relevant ones'}
Target word count: ~{word_count} words
Target audience: {audience or 'General web user'}
Extra notes: {extra_notes or 'None'}

Write the full SEO-optimised content now.
"""
    result = await call_llm_json(
        [{"role": "system", "content": system}, {"role": "user", "content": human}],
        temperature=0.4,
    )
    log.info("seo_content_written", keyword=target_keyword)
    return json.dumps(result, indent=2)
