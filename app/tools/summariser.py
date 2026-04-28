"""
Summarisation tools.

summarise     – summarise any text passed directly.
summarise_url – fetch a web page / article and summarise it in one step.

Both return a structured JSON with the summary, key points, and metadata.
"""
import json

import structlog

from app.agent.llm_client import call_llm_json

log = structlog.get_logger(__name__)

_SUMMARY_SYSTEM = """\
You are an expert summariser. Produce a clean, accurate summary of the provided text.

Return ONLY a JSON object – no markdown fences:
{
  "title":       "<inferred or provided title>",
  "summary":     "<concise summary in the requested style>",
  "key_points":  ["<most important point>", "…"],
  "word_count":  <word count of the summary>,
  "sentiment":   "<positive|neutral|negative|mixed>",
  "topics":      ["<main topic tags>"]
}

Style guide:
  bullets    → bullet-point summary with 5-8 items (use the key_points array for this)
  paragraph  → flowing prose summary in 3-5 sentences
  executive  → exec-summary format: situation, key findings, recommendation
  eli5       → explain like I'm 5 – plain language, no jargon
  tldr       → Twitter-length (≤280 chars), single sentence
"""

_MAX_INPUT_CHARS = 40_000   # ~10k tokens


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) > _MAX_INPUT_CHARS:
        return text[:_MAX_INPUT_CHARS], True
    return text, False


async def summarise(
    text: str,
    style: str = "bullets",
    max_length: int = 300,
    focus: str = "",
    title: str = "",
) -> str:
    """
    Summarise any text.

    Args:
        text:       The content to summarise (article, transcript, document, etc.).
        style:      Output style – bullets | paragraph | executive | eli5 | tldr.
        max_length: Approximate max word count for the summary (default 300).
        focus:      Optional angle to focus on (e.g. "business implications").
        title:      Optional title/label for the source content.

    Returns:
        JSON string with summary, key_points, sentiment, and topics.
    """
    if not text or not text.strip():
        return json.dumps({"status": "error", "message": "No text provided."}, indent=2)

    truncated_text, was_truncated = _truncate(text)
    log.info("summarise", style=style, chars=len(text), truncated=was_truncated)

    human = f"""\
{f'Title: {title}' if title else ''}
Style: {style}
Max summary length: ~{max_length} words
Focus: {focus or 'General – cover the most important points'}
{'[Note: source text was truncated to fit context limit]' if was_truncated else ''}

Text to summarise:
---
{truncated_text}
---

Produce the summary now.
"""
    result = await call_llm_json(
        [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": human},
        ],
        temperature=0.2,
    )
    result["source_length_words"] = len(text.split())
    result["truncated"] = was_truncated
    log.info("summarise_done", words=result.get("word_count", 0))
    return json.dumps(result, indent=2)


async def summarise_url(
    url: str,
    style: str = "bullets",
    max_length: int = 300,
    focus: str = "",
) -> str:
    """
    Fetch a web page or article and summarise it in one step.

    Args:
        url:        Full URL of the article or web page.
        style:      Output style – bullets | paragraph | executive | eli5 | tldr.
        max_length: Approximate max word count for the summary.
        focus:      Optional angle to focus on.

    Returns:
        JSON string with summary, key_points, and the source URL.
    """
    log.info("summarise_url", url=url[:80], style=style)

    # Reuse document_reader for content extraction
    from app.tools.document_reader import read_document

    raw = await read_document(source=url)
    doc = json.loads(raw)

    if doc.get("status") == "error":
        return json.dumps({
            "status": "error",
            "url": url,
            "message": doc.get("message", "Failed to fetch the URL."),
        }, indent=2)

    content = doc.get("content", "")
    page_title = doc.get("title", "")

    result_json = await summarise(
        text=content,
        style=style,
        max_length=max_length,
        focus=focus,
        title=page_title,
    )
    result = json.loads(result_json)
    result["url"] = url
    result["page_title"] = page_title
    return json.dumps(result, indent=2)
