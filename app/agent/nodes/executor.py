"""
Executor node: runs a single step from the plan by dispatching to the tool
registry. Handles placeholder resolution and approval gating.
"""
import json
import re

import structlog

from app.agent.llm_client import active_model
from app.agent.llm_router import route_llm
from app.agent.state import AgentState, StepResult
from app.safety.approval import (
    check_approval_status,
    create_approval_request,
    create_user_input_request,
    get_user_input_answer,
)
from app.tools import TOOL_REGISTRY

log = structlog.get_logger(__name__)


def _resolve_placeholders(tool_input: dict, step_results: list[StepResult]) -> dict:
    """
    Replace __step_N_output__ placeholders in tool_input with actual outputs
    from previous steps.
    """
    resolved = {}
    for key, value in tool_input.items():
        if isinstance(value, str):
            def replacer(match):
                step_n = int(match.group(1))
                for result in step_results:
                    if result["step_number"] == step_n:
                        output = result.get("output", "")
                        return str(output) if not isinstance(output, str) else output
                return match.group(0)  # Keep placeholder if not found

            resolved[key] = re.sub(r"__step_(\d+)_output__", replacer, value)
        else:
            resolved[key] = value
    return resolved


async def executor_node(state: AgentState) -> dict:
    task_id = state["task_id"]
    plan = state["plan"]
    current_idx = state["current_step_idx"]
    step_results = state.get("step_results", [])

    if current_idx >= len(plan):
        # All steps done – signal the router
        return {"status": "reviewing"}

    step = plan[current_idx]
    step_number = step.get("step_number", current_idx + 1)
    tool_name = step["tool_name"]

    log.info(
        "executor_step_start",
        task_id=task_id,
        step=step_number,
        tool=tool_name,
    )

    # ── Ask-user gate ────────────────────────────────────────────────────────
    if tool_name == "ask_user":
        question = step.get("tool_input", {}).get("question", "Please provide more information.")

        answer = await get_user_input_answer(task_id, step_number)
        if answer is not None:
            log.info("ask_user_answered", task_id=task_id, step=step_number)
            result = StepResult(
                step_number=step_number,
                tool_name=tool_name,
                status="success",
                output=answer,
                error=None,
            )
            final_output = state.get("final_output", "")
            return {
                "step_results": [result],
                "current_step_idx": current_idx + 1,
                "final_output": final_output,
                "pending_approval": None,
            }

        input_id = await create_user_input_request(task_id, step_number, question)
        log.info("ask_user_waiting", task_id=task_id, step=step_number, input_id=input_id)
        return {
            "status": "waiting_for_input",
            "pending_approval": {
                "approval_id": input_id,
                "step_number": step_number,
                "action_type": "user_input",
                "action_payload": {"question": question},
                "action_summary": question,
            },
        }

    # ── Safety gate ──────────────────────────────────────────────────────────
    if step.get("requires_approval", False):
        approval_status = await check_approval_status(task_id, step_number)

        if approval_status is None:
            # No approval record yet – create one and pause
            approval_id = await create_approval_request(
                task_id=task_id,
                step_number=step_number,
                action_type=tool_name,
                action_payload=step.get("tool_input", {}),
                action_summary=step.get("description", ""),
            )
            log.info("approval_requested", task_id=task_id, approval_id=approval_id)
            return {
                "status": "pending_approval",
                "pending_approval": {
                    "approval_id": approval_id,
                    "step_number": step_number,
                    "action_type": tool_name,
                    "action_payload": step.get("tool_input", {}),
                    "action_summary": step.get("description", ""),
                },
            }

        if approval_status == "rejected":
            log.warning("step_rejected", task_id=task_id, step=step_number)
            return {
                "status": "rejected",
                "step_results": [
                    StepResult(
                        step_number=step_number,
                        tool_name=tool_name,
                        status="skipped",
                        output=None,
                        error="Rejected by approver",
                    )
                ],
            }

        # approval_status == "approved" → fall through to execution

    # ── Resolve placeholders and call tool ──────────────────────────────────
    raw_input = step.get("tool_input", {})
    resolved_input = _resolve_placeholders(raw_input, step_results)

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        error_msg = f"Unknown tool: {tool_name}"
        log.error("unknown_tool", task_id=task_id, tool=tool_name)
        return {
            "step_results": [
                StepResult(
                    step_number=step_number,
                    tool_name=tool_name,
                    status="failed",
                    output=None,
                    error=error_msg,
                )
            ],
            "current_step_idx": current_idx + 1,
            "errors": [error_msg],
        }

    # ── LLM routing ─────────────────────────────────────────────────────────
    routed_model = await route_llm(
        tool_name=tool_name,
        tool_input=resolved_input,
        task_description=state.get("user_task", ""),
    )
    ctx_token = active_model.set(routed_model) if routed_model else None

    try:
        output = await tool_fn(**resolved_input)
        log.info("step_success", task_id=task_id, step=step_number, tool=tool_name, model=routed_model or "default")
        result = StepResult(
            step_number=step_number,
            tool_name=tool_name,
            status="success",
            output=output,
            error=None,
        )
    except Exception as exc:
        log.error("step_failed", task_id=task_id, step=step_number, error=str(exc))
        result = StepResult(
            step_number=step_number,
            tool_name=tool_name,
            status="failed",
            output=None,
            error=str(exc),
        )
    finally:
        if ctx_token is not None:
            active_model.reset(ctx_token)

    # Compose final_output from the last successful content-producing step
    final_output = state.get("final_output", "")
    if result["status"] == "success" and isinstance(result["output"], str):
        final_output = result["output"]

    return {
        "step_results": [result],
        "current_step_idx": current_idx + 1,
        "final_output": final_output,
        "pending_approval": None,
    }
