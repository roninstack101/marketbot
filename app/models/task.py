"""
SQLAlchemy ORM models.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_task: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=True)

    # Lifecycle status: pending | running | pending_approval | complete | failed | rejected
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)

    # Agent internals stored as JSON so we can resume interrupted graphs
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    step_results: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    agent_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Final deliverables
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_version: Mapped[int] = mapped_column(Integer, default=1)
    critique: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="task", cascade="all, delete-orphan"
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tasks.id"), nullable=False, index=True
    )

    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    task: Mapped["Task"] = relationship("Task", back_populates="approvals")


class Memory(Base):
    """Stores summarised task outcomes for future retrieval."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    task_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True
    )
    task_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    task_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
