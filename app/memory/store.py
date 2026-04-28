"""
Memory store: saves task outcomes and retrieves relevant past context.

Uses simple keyword matching (ILIKE) for retrieval. If you enable pgvector
in PostgreSQL, you can replace retrieve_relevant_memories with a cosine
similarity search on embeddings – the interface stays the same.
"""
from typing import Any

import structlog
from sqlalchemy import or_, select

from app.database import get_async_db, get_sync_db
from app.models.task import Memory, Task

log = structlog.get_logger(__name__)


async def retrieve_relevant_memories(
    user_task: str,
    limit: int = 3,
    task_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return up to `limit` past memories most relevant to `user_task`.
    Relevance is determined by keyword overlap (async, for the planner node).
    """
    # Extract meaningful keywords: words > 4 chars, exclude stop words
    stop_words = {"will", "would", "should", "could", "write", "create", "make",
                  "generate", "using", "with", "from", "that", "this", "have"}
    keywords = [
        w.lower()
        for w in user_task.split()
        if len(w) > 4 and w.lower() not in stop_words
    ][:6]  # Top 6 keywords

    if not keywords:
        return []

    conditions = [
        or_(
            Memory.task_summary.ilike(f"%{kw}%"),
            Memory.output_summary.ilike(f"%{kw}%"),
        )
        for kw in keywords
    ]

    async with get_async_db() as session:
        stmt = (
            select(Memory)
            .where(or_(*conditions))
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        if task_type:
            stmt = stmt.where(Memory.task_type == task_type)

        rows = (await session.execute(stmt)).scalars().all()

    memories = [
        {
            "id": r.id,
            "task_summary": r.task_summary,
            "output_summary": r.output_summary[:500],
            "task_type": r.task_type,
        }
        for r in rows
    ]

    log.debug("memory_retrieved", count=len(memories), keywords=keywords[:3])
    return memories


def save_task_memory_sync(
    task_id: str,
    user_task: str,
    final_output: str,
    task_type: str = "general",
) -> None:
    """
    Called from the Celery worker (sync context) after a task completes
    to persist the outcome for future retrieval.
    """
    summary = user_task[:200]
    output_summary = final_output[:1000] if final_output else "No output"

    with get_sync_db() as session:
        memory = Memory(
            task_id=task_id,
            task_type=task_type,
            task_summary=summary,
            output_summary=output_summary,
            keywords=summary.lower().split()[:10],
        )
        session.add(memory)

    log.info("memory_saved", task_id=task_id)
