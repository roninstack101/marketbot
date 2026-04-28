"""
LangGraph StateGraph definition for ClaudBot.

Flow:
  START
    └─▶ planner     (break task into steps, retrieve memory)
          └─▶ executor  (run current step, dispatch to tool)
                ├─▶ executor    (loop: more steps remaining)
                ├─▶ critic      (all steps done)
                └─▶ END         (pending_approval | failed | rejected)
          executor ◀─┤
  critic  ├─▶ executor  (revise: reset and re-run)
          └─▶ END        (complete)
"""
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.critic import critic_node
from app.agent.nodes.executor import executor_node
from app.agent.nodes.planner import planner_node
from app.agent.state import AgentState


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_executor(state: AgentState) -> str:
    status = state.get("status", "running")

    if status in ("pending_approval", "waiting_for_input", "rejected", "failed"):
        return "end"

    plan = state.get("plan", [])
    current_idx = state.get("current_step_idx", 0)

    if current_idx < len(plan):
        return "continue"   # More steps to run

    return "review"         # All steps done, hand off to critic


def route_after_critic(state: AgentState) -> str:
    status = state.get("status", "running")

    if status == "complete":
        return "end"

    # revision_count was already incremented by the critic node
    # If it reset current_step_idx, we re-enter executor
    return "revise"


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "continue": "executor",
            "review": "critic",
            "end": END,
        },
    )

    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "end": END,
            "revise": "executor",
        },
    )

    return graph


# Compiled graph is reused across all invocations (thread-safe)
compiled_graph = build_graph().compile()


async def run_agent(
    task_id: str,
    user_task: str,
    existing_state: dict | None = None,
) -> AgentState:
    """
    Run the agent graph from scratch or resume from a saved state.

    `existing_state` is used when resuming after an approval: pass the
    previously saved state so the executor re-evaluates the approval gate
    (which will now return 'approved').
    """
    if existing_state:
        initial_state = existing_state
    else:
        initial_state = AgentState(
            task_id=task_id,
            user_task=user_task,
            plan=[],
            current_step_idx=0,
            memory_context="",
            step_results=[],
            pending_approval=None,
            final_output="",
            critique=None,
            revision_count=0,
            status="running",
            errors=[],
        )

    result = await compiled_graph.ainvoke(initial_state)
    return result
