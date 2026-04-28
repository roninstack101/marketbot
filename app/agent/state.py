"""
Typed state that flows through the LangGraph agent graph.

All fields must be JSON-serialisable so the state can be checkpointed
to PostgreSQL and resumed after an approval gate.
"""
import operator
from typing import Annotated, Any, Optional, TypedDict


class Step(TypedDict):
    step_number: int
    description: str          # Human-readable description
    tool_name: str            # Which tool to call
    tool_input: dict          # Parameters to pass to the tool
    requires_approval: bool   # Whether this step needs human sign-off


class StepResult(TypedDict):
    step_number: int
    tool_name: str
    status: str               # success | failed | skipped
    output: Any
    error: Optional[str]


class ApprovalRequest(TypedDict):
    approval_id: str
    step_number: int
    action_type: str
    action_payload: dict
    action_summary: str


class AgentState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    task_id: str
    user_task: str

    # ── Planning ──────────────────────────────────────────────────────────────
    plan: list[Step]
    current_step_idx: int
    memory_context: str       # Relevant past tasks retrieved from DB

    # ── Execution ─────────────────────────────────────────────────────────────
    # Annotated with operator.add so each node can append without overwriting
    step_results: Annotated[list[StepResult], operator.add]

    # ── Safety ────────────────────────────────────────────────────────────────
    pending_approval: Optional[ApprovalRequest]

    # ── Critic ────────────────────────────────────────────────────────────────
    final_output: str
    critique: Optional[str]
    revision_count: int       # Guard against infinite critique-revise loops

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    status: str               # pending | running | pending_approval | complete | failed
    errors: Annotated[list[str], operator.add]
