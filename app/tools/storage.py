"""
Data storage tools – persist and retrieve agent outputs in the DB.
  store_data    – saves a key/value record
  retrieve_data – fetches records by key or text search
  delete_data   – removes records         ⚠ REQUIRES APPROVAL
"""
import json
from datetime import datetime, timezone

import structlog

from app.database import get_sync_db
from app.models.task import Memory

log = structlog.get_logger(__name__)


async def store_data(
    key: str,
    value: str,
    task_type: str = "general",
    task_id: str | None = None,
) -> str:
    """
    Store a key/value record in the memories table for later retrieval.

    Args:
        key:       Short identifier (used as task_summary).
        value:     Content to store (used as output_summary).
        task_type: Category tag (campaign | email | report | general).
        task_id:   Optional parent task ID.

    Returns:
        Confirmation with the new memory ID.
    """
    log.info("store_data", key=key[:60], task_type=task_type)

    with get_sync_db() as session:
        memory = Memory(
            task_id=task_id,
            task_type=task_type,
            task_summary=key,
            output_summary=value[:4000],  # Guard against very large values
            keywords=[],
            metadata_={"stored_at": datetime.now(timezone.utc).isoformat()},
        )
        session.add(memory)
        session.flush()
        memory_id = memory.id

    log.info("data_stored", memory_id=memory_id)
    return f"Data stored successfully. Memory ID: {memory_id}"


async def retrieve_data(
    query: str,
    task_type: str | None = None,
    limit: int = 5,
) -> str:
    """
    Retrieve stored records by text similarity (simple ILIKE search).

    Args:
        query:     Search terms to match against task_summary.
        task_type: Optional filter by category.
        limit:     Maximum records to return.

    Returns:
        JSON array of matching records.
    """
    log.info("retrieve_data", query=query[:60])

    from sqlalchemy import or_, select, text

    with get_sync_db() as session:
        stmt = (
            select(Memory)
            .where(
                or_(
                    Memory.task_summary.ilike(f"%{query}%"),
                    Memory.output_summary.ilike(f"%{query}%"),
                )
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        if task_type:
            stmt = stmt.where(Memory.task_type == task_type)

        rows = session.execute(stmt).scalars().all()

    results = [
        {
            "id": r.id,
            "key": r.task_summary,
            "value": r.output_summary,
            "task_type": r.task_type,
            "stored_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    log.info("data_retrieved", count=len(results))
    return json.dumps(results, indent=2)


async def delete_data(
    memory_id: str,
) -> str:
    """
    Permanently delete a stored record.  ⚠ This tool requires approval.

    Args:
        memory_id: UUID of the memory record to delete.

    Returns:
        Confirmation string.
    """
    log.warning("delete_data", memory_id=memory_id)

    from sqlalchemy import delete

    with get_sync_db() as session:
        result = session.execute(
            delete(Memory).where(Memory.id == memory_id)
        )
        deleted = result.rowcount

    if deleted == 0:
        raise ValueError(f"No record found with ID: {memory_id}")

    log.info("data_deleted", memory_id=memory_id)
    return f"Record {memory_id} deleted successfully."
