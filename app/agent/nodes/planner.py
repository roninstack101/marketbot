"""
Planner node: converts a free-text user task into a structured step plan.
Also retrieves relevant memories to give the LLM prior-task context.
"""
import json

import structlog

from app.agent.llm_client import call_llm_json
from app.agent.prompts.planner import PLANNER_HUMAN, PLANNER_SYSTEM
from app.agent.state import AgentState
from app.memory.store import retrieve_relevant_memories
from app.memory.user_store import format_user_memory_context

log = structlog.get_logger(__name__)


async def planner_node(state: AgentState) -> dict:
    task_id = state["task_id"]
    user_task = state["user_task"]

    log.info("planner_start", task_id=task_id)

    # ── Retrieve memory context ───────────────────────────────────────────────
    try:
        memories = await retrieve_relevant_memories(user_task, limit=3)
        memory_context = "\n\n".join(
            f"Task: {m['task_summary']}\nOutcome: {m['output_summary']}"
            for m in memories
        ) or "No relevant past tasks found."
    except Exception as exc:
        log.warning("memory_retrieval_failed", error=str(exc))
        memory_context = "Memory unavailable."

    # ── Call LLM ─────────────────────────────────────────────────────────────
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {
            "role": "user",
            "content": PLANNER_HUMAN.format(
                memory_context=memory_context,
                user_task=user_task,
            ),
        },
    ]

    try:
        plan_data = await call_llm_json(messages)
    except Exception as exc:
        log.error("planner_llm_failed", task_id=task_id, error=str(exc))
        return {
            "status": "failed",
            "errors": [f"Planner failed: {exc}"],
            "plan": [],
            "memory_context": memory_context,
        }

    steps = plan_data.get("steps", [])
    log.info("plan_created", task_id=task_id, step_count=len(steps))

    return {
        "plan": steps,
        "memory_context": memory_context,
        "current_step_idx": 0,
        "status": "running",
    }
