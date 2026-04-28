"""
Critic node: evaluates the agent's output and either approves it or
requests targeted revisions (capped at MAX_REVISIONS to prevent loops).
"""
import json

import structlog

from app.agent.llm_client import call_llm_json
from app.agent.prompts.critic import CRITIC_HUMAN, CRITIC_SYSTEM
from app.agent.state import AgentState

log = structlog.get_logger(__name__)

MAX_REVISIONS = 2  # Maximum number of critic-executor cycles


async def critic_node(state: AgentState) -> dict:
    task_id = state["task_id"]
    revision_count = state.get("revision_count", 0)
    step_results = state.get("step_results", [])

    log.info("critic_start", task_id=task_id, revision=revision_count)

    # Summarise step results for the prompt
    results_text = "\n".join(
        f"Step {r['step_number']} ({r['tool_name']}): "
        f"{'✓' if r['status'] == 'success' else '✗'} "
        f"{json.dumps(r['output'])[:400] if r['output'] else r.get('error', '')}"
        for r in step_results
    )

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM},
        {
            "role": "user",
            "content": CRITIC_HUMAN.format(
                user_task=state["user_task"],
                step_results=results_text,
                final_output=state.get("final_output", ""),
                critique=state.get("critique") or "None",
            ),
        },
    ]

    try:
        evaluation = await call_llm_json(messages)
    except Exception as exc:
        log.error("critic_llm_failed", task_id=task_id, error=str(exc))
        # On failure, approve as-is to avoid blocking the pipeline
        return {
            "status": "complete",
            "critique": f"Critic failed: {exc}",
        }

    verdict = evaluation.get("verdict", "approve")
    score = evaluation.get("score", 8)
    final_output = evaluation.get("final_output", state.get("final_output", ""))

    log.info("critic_verdict", task_id=task_id, verdict=verdict, score=score)

    if verdict == "revise" and revision_count < MAX_REVISIONS:
        improvements = evaluation.get("improvements", [])
        critique_text = (
            f"Score: {score}/10\n"
            f"Summary: {evaluation.get('summary', '')}\n"
            f"Improvements:\n" + "\n".join(f"- {i}" for i in improvements)
        )
        return {
            "critique": critique_text,
            "revision_count": revision_count + 1,
            "final_output": final_output,
            # Reset step index so executor re-runs from step 0 with the critique in context
            "current_step_idx": 0,
            "step_results": [],  # Clear results for fresh revision run
        }

    # Approve
    return {
        "status": "complete",
        "final_output": final_output,
        "critique": evaluation.get("summary", ""),
    }
