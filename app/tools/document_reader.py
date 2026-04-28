"""
Document reader tool.

read_document accepts:
  - Local file path  : PDF (.pdf), plain text (.txt / .md / .csv / .json)
  - Web URL          : fetches the page and extracts article text

Requires pdfplumber (pip install pdfplumber) for PDF support.
Requires beautifulsoup4 + lxml for URL/HTML extraction.
"""
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger(__name__)

_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
_MAX_CHARS = 50_000   # ~12k tokens — plenty for most LLM contexts
_MAX_PDF_PAGES = 50


def _is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https")


def _read_text_file(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    return {
        "type": "text",
        "source": str(path),
        "word_count": len(content.split()),
        "content": content[:_MAX_CHARS],
        "truncated": len(content) > _MAX_CHARS,
    }


def _read_pdf(path: Path, max_pages: int) -> dict[str, Any]:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber is not installed. Run: pip install pdfplumber"
        )

    pages_text: list[str] = []
    total_pages = 0

    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)
        for page in pdf.pages[:max_pages]:
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(text)

    full_text = "\n\n".join(pages_text)
    return {
        "type": "pdf",
        "source": str(path),
        "total_pages": total_pages,
        "pages_read": min(max_pages, total_pages),
        "word_count": len(full_text.split()),
        "content": full_text[:_MAX_CHARS],
        "truncated": len(full_text) > _MAX_CHARS or total_pages > max_pages,
    }


async def _read_url(url: str) -> dict[str, Any]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError(
            "beautifulsoup4 is not installed. Run: pip install beautifulsoup4 lxml"
        )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; ClaudBot/1.0; +https://github.com/claudbot)"
        )
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        html = response.text

    soup = BeautifulSoup(html, "lxml")

    # Strip boilerplate
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "form", "noscript", "iframe", "ads",
                     "advertisement", "cookie-banner"]):
        tag.decompose()

    # Try to find the main article body
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find(class_="content")
        or soup.find(class_="post-body")
        or soup.body
    )

    raw = (main or soup).get_text(separator="\n", strip=True)

    # Collapse blank lines
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    content = "\n".join(lines)

    title = ""
    if soup.title:
        title = soup.title.string or ""

    return {
        "type": "url",
        "source": url,
        "title": title.strip(),
        "word_count": len(content.split()),
        "content": content[:_MAX_CHARS],
        "truncated": len(content) > _MAX_CHARS,
    }


async def read_document(
    source: str,
    max_pages: int = 50,
) -> str:
    """
    Extract text from a PDF, plain-text file, or web URL.

    Args:
        source:    One of:
                   • A filename in the uploads/ folder (e.g. "report.pdf", "brief.txt")
                   • An absolute local path (e.g. "/tmp/doc.pdf")
                   • A full web URL  (e.g. "https://example.com/article")
        max_pages: Max PDF pages to read (default 50). Ignored for other types.

    Returns:
        JSON string with content, word count, and metadata.
        The 'content' field contains the extracted text ready for summarise or
        any content-writing tool.
    """
    log.info("read_document", source=source[:100])

    if _is_url(source):
        data = await _read_url(source)
        log.info("document_read", type="url", words=data["word_count"])
        return json.dumps(data, indent=2)

    # Resolve local path
    path = Path(source)
    if not path.is_absolute():
        path = _UPLOAD_DIR / source

    if not path.exists():
        return json.dumps({
            "status": "error",
            "message": (
                f"File not found: '{source}'. "
                f"Place the file in the uploads/ folder or provide a full path."
            ),
        }, indent=2)

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        data = _read_pdf(path, max_pages)
    elif suffix in (".txt", ".md", ".csv", ".json", ".html", ".htm", ".rst"):
        data = _read_text_file(path)
    else:
        # Try as plain text for unknown extensions
        try:
            data = _read_text_file(path)
        except Exception:
            return json.dumps({
                "status": "error",
                "message": f"Unsupported file type: {suffix}. Supported: .pdf, .txt, .md, .csv, .json",
            }, indent=2)

    log.info("document_read", type=data["type"], words=data["word_count"])
    return json.dumps(data, indent=2)
