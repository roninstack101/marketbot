"""
Approval gate helpers.

The executor calls these to create an approval request and to check
whether a pending approval has been resolved.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update

from app.database import get_async_db, get_sync_db
from app.models.task import Approval, Task

log = structlog.get_logger(__name__)


async def create_approval_request(
    task_id: str,
    step_number: int,
    action_type: str,
    action_payload: dict,
    action_summary: str,
) -> str:
    """
    Persist an Approval record and return its ID.
    Also updates the parent Task status to 'pending_approval'.
    """
    async with get_async_db() as session:
        # Check an approval for this step doesn't already exist
        existing = (
            await session.execute(
                select(Approval).where(
                    Approval.task_id == task_id,
                    Approval.action_type == action_type,
                    Approval.status == "pending",
                )
            )
        ).scalar_one_or_none()

        if existing:
            return existing.id

        approval = Approval(
            id=str(uuid.uuid4()),
            task_id=task_id,
            action_type=action_type,
            action_payload=action_payload,
            action_summary=action_summary,
            status="pending",
        )
        session.add(approval)

        # Update parent task status
        await session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status="pending_approval")
        )

        await session.flush()
        approval_id = approval.id

    log.info("approval_created", task_id=task_id, approval_id=approval_id)
    return approval_id


async def check_approval_status(
    task_id: str,
    step_number: int,
) -> Optional[str]:
    """
    Returns:
      None        – no approval record exists for this task/step
      'pending'   – exists but not yet decided (treat as None for gating)
      'approved'  – go ahead
      'rejected'  – stop
    """
    async with get_async_db() as session:
        result = (
            await session.execute(
                select(Approval).where(
                    Approval.task_id == task_id,
                    Approval.status.in_(["pending", "approved", "rejected"]),
                )
            )
        ).scalars().all()

    if not result:
        return None

    # If any approval for this task is still pending, block
    for approval in result:
        if approval.status == "pending":
            return "pending"
        if approval.status == "rejected":
            return "rejected"

    return "approved"


def resolve_approval_sync(
    approval_id: str,
    decision: str,
    approved_by: str,
    rejection_reason: Optional[str] = None,
) -> None:
    """
    Called by the API handler when a user approves or rejects.
    Sync version for use from FastAPI via run_in_executor if needed,
    but we'll use it from an async wrapper.
    """
    now = datetime.now(timezone.utc)

    with get_sync_db() as session:
        approval = session.get(Approval, approval_id)
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        approval.status = decision
        approval.approved_by = approved_by
        approval.resolved_at = now
        if rejection_reason:
            approval.rejection_reason = rejection_reason

    log.info("approval_resolved", approval_id=approval_id, decision=decision)
