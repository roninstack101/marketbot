"""
Pydantic v2 request/response schemas for the API layer.
"""
import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    user_task: str = Field(
        ...,
        min_length=5,
        description="Natural language description of the task to execute",
        examples=["Write a Q2 email campaign for our summer sale"],
    )
    created_by: Optional[str] = Field(None, description="Identifier of the user or system submitting the task")
    user_id: Optional[str] = Field(None, description="User identifier for personal memory lookup")


class TaskResponse(BaseModel):
    id: str
    user_task: str
    status: str
    plan: Optional[list] = None
    step_results: Optional[list] = None
    final_output: Optional[str] = None
    output_version: int = 1
    critique: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("plan", "step_results", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v


class TaskStatusResponse(BaseModel):
    id: str
    status: str
    message: str
    pending_approval_id: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Approval ──────────────────────────────────────────────────────────────────

class ApprovalResponse(BaseModel):
    id: str
    task_id: str
    action_type: str
    action_payload: dict
    action_summary: Optional[str] = None
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., description="Name or ID of the approver")
    rejection_reason: Optional[str] = Field(
        None, description="Required when rejecting"
    )


# ── User input (ask_user tool) ────────────────────────────────────────────────

class UserInputRequest(BaseModel):
    answer: str = Field(..., description="The user's answer to the bot's question")


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryResponse(BaseModel):
    id: str
    task_id: Optional[str] = None
    task_type: Optional[str] = None
    task_summary: str
    output_summary: str
    keywords: Optional[list] = None
    created_at: datetime

    model_config = {"from_attributes": True}
