"""
Memory / history endpoints:
  GET /history          List stored memories
  GET /history/search   Search memories by keyword
"""
import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import Memory
from app.schemas.task import MemoryResponse

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/history", tags=["History"])


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    task_type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Memory)
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    if task_type:
        stmt = stmt.where(Memory.task_type == task_type)

    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/search", response_model=list[MemoryResponse])
async def search_memories(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Full-text keyword search across memory summaries."""
    stmt = (
        select(Memory)
        .where(
            or_(
                Memory.task_summary.ilike(f"%{q}%"),
                Memory.output_summary.ilike(f"%{q}%"),
            )
        )
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows
