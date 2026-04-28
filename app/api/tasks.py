"""
Task endpoints:
  POST   /tasks            Submit a new task
  GET    /tasks            List recent tasks
  GET    /tasks/{id}       Get task details + output
  DELETE /tasks/{id}       Cancel a pending task
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse, TaskStatusResponse
from app.worker.tasks import execute_task

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=TaskStatusResponse, status_code=202)
async def submit_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a natural-language task for the agent to execute.
    Returns immediately with a task_id; execution is asynchronous.
    Poll GET /tasks/{id} to check status and retrieve the output.
    """
    task_id = str(uuid.uuid4())

    task = Task(
        id=task_id,
        user_task=payload.user_task,
        created_by=payload.created_by,
        status="pending",
    )
    db.add(task)
    await db.flush()

    # Dispatch to Celery worker
    execute_task.delay(
        task_id=task_id,
        user_task=payload.user_task,
        created_by=payload.created_by,
    )

    log.info("task_submitted", task_id=task_id, user=payload.created_by)

    return TaskStatusResponse(
        id=task_id,
        status="pending",
        message="Task accepted. Poll /tasks/{id} for progress.",
    )


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List tasks, most recent first."""
    stmt = (
        select(Task)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(Task.status == status)

    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a task including output and step results."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}", response_model=TaskStatusResponse)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a task that is still pending (cannot cancel a running task)."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("pending",):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel task in '{task.status}' state.",
        )

    task.status = "cancelled"
    log.info("task_cancelled", task_id=task_id)

    return TaskStatusResponse(
        id=task_id,
        status="cancelled",
        message="Task cancelled.",
    )
