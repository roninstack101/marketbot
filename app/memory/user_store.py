"""
Per-user persistent memory store.
Each user (identified by Telegram chat_id or any string) gets their own
isolated set of memory entries that persist across sessions.
"""
import uuid

import structlog
from sqlalchemy import delete, select

from app.database import get_async_db, get_sync_db
from app.models.task import UserMemory

log = structlog.get_logger(__name__)


async def save_user_memory(user_id: str, memory: str, category: str = "fact") -> str:
    """Save a new memory entry for a user. Returns the memory ID."""
    async with get_async_db() as session:
        entry = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            category=category,
            memory=memory,
        )
        session.add(entry)
        await session.flush()
        mem_id = entry.id

    log.info("user_memory_saved", user_id=user_id, category=category)
    return mem_id


async def get_user_memories(user_id: str) -> list[dict]:
    """Retrieve all memories for a user, newest first."""
    async with get_async_db() as session:
        rows = (
            await session.execute(
                select(UserMemory)
                .where(UserMemory.user_id == user_id)
                .order_by(UserMemory.created_at.desc())
            )
        ).scalars().all()

    return [
        {"id": r.id, "category": r.category, "memory": r.memory, "created_at": str(r.created_at)}
        for r in rows
    ]


async def delete_user_memory(memory_id: str, user_id: str) -> bool:
    """Delete a specific memory entry. Returns True if deleted."""
    async with get_async_db() as session:
        result = await session.execute(
            delete(UserMemory).where(
                UserMemory.id == memory_id,
                UserMemory.user_id == user_id,
            )
        )
    deleted = result.rowcount > 0
    if deleted:
        log.info("user_memory_deleted", memory_id=memory_id, user_id=user_id)
    return deleted


async def clear_user_memories(user_id: str) -> int:
    """Delete all memories for a user. Returns count deleted."""
    async with get_async_db() as session:
        result = await session.execute(
            delete(UserMemory).where(UserMemory.user_id == user_id)
        )
    count = result.rowcount
    log.info("user_memories_cleared", user_id=user_id, count=count)
    return count


async def format_user_memory_context(user_id: str) -> str:
    """
    Return a formatted string of all user memories for injection into
    the planner prompt. Returns empty string if no memories exist.
    """
    memories = await get_user_memories(user_id)
    if not memories:
        return ""

    lines = [f"- [{m['category']}] {m['memory']}" for m in memories]
    return "## About this user\n" + "\n".join(lines)


def save_user_memory_sync(user_id: str, memory: str, category: str = "fact") -> str:
    """Sync version for use in Celery workers."""
    with get_sync_db() as session:
        entry = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            category=category,
            memory=memory,
        )
        session.add(entry)
        mem_id = entry.id
    return mem_id
