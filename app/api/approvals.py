"""
Approval endpoints:
  GET    /approvals              List pending approvals
  GET    /approvals/{id}         Get approval details
  POST   /approvals/{id}/approve Approve an action
  POST   /approvals/{id}/reject  Reject an action
"""
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import Approval
from app.schemas.task import ApprovalResponse, ApproveRequest
from app.worker.tasks import resume_task

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    status: str = "pending",
    db: AsyncSession = Depends(get_db),
):
    """List approvals filtered by status (default: pending)."""
    rows = (
        await db.execute(
            select(Approval)
            .where(Approval.status == status)
            .order_by(Approval.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    approval = await db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_action(
    approval_id: str,
    body: ApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a pending action.
    This immediately re-queues the parent task to continue execution.
    """
    approval = await db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already '{approval.status}'.",
        )

    approval.status = "approved"
    approval.approved_by = body.approved_by
    approval.resolved_at = datetime.now(timezone.utc)
    await db.flush()

    # Resume the parent task in a worker
    resume_task.delay(
        task_id=approval.task_id,
        approved_by=body.approved_by,
    )

    log.info("approval_approved", approval_id=approval_id, by=body.approved_by)
    return approval


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_action(
    approval_id: str,
    body: ApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a pending action. The parent task will be marked as 'rejected'.
    """
    if not body.rejection_reason:
        raise HTTPException(
            status_code=422,
            detail="rejection_reason is required when rejecting.",
        )

    approval = await db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval is already '{approval.status}'.",
        )

    approval.status = "rejected"
    approval.approved_by = body.approved_by
    approval.rejection_reason = body.rejection_reason
    approval.resolved_at = datetime.now(timezone.utc)
    await db.flush()

    # Also update the parent task
    from sqlalchemy import update
    from app.models.task import Task
    await db.execute(
        update(Task)
        .where(Task.id == approval.task_id)
        .values(status="rejected", error=f"Rejected: {body.rejection_reason}")
    )

    log.info("approval_rejected", approval_id=approval_id, by=body.approved_by)
    return approval
