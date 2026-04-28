"""
Integration tests for the LangGraph agent pipeline.
All LLM calls are mocked; DB calls use an in-memory SQLite.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.state import AgentState


# ── Planner node ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_planner_creates_plan():
    mock_plan = {
        "task_type": "campaign",
        "summary": "Create a summer sale campaign",
        "steps": [
            {
                "step_number": 1,
                "description": "Generate campaign copy",
                "tool_name": "generate_campaign",
                "tool_input": {
                    "product": "Summer Collection",
                    "goal": "drive sales",
                    "audience": "existing customers",
                },
                "requires_approval": False,
            }
        ],
    }

    with (
        patch("app.agent.llm_client.call_llm_json", new_callable=AsyncMock, return_value=mock_plan),
        patch("app.memory.store.retrieve_relevant_memories", new_callable=AsyncMock, return_value=[]),
    ):
        from app.agent.nodes.planner import planner_node

        state = AgentState(
            task_id="test-123",
            user_task="Create a summer sale campaign",
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

        result = await planner_node(state)

    assert len(result["plan"]) == 1
    assert result["plan"][0]["tool_name"] == "generate_campaign"
    assert result["status"] == "running"


# ── Executor node ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_calls_correct_tool():
    mock_campaign_output = json.dumps({"subject": "Summer Sale!", "body": "..."})

    with (
        patch("app.tools.campaign.generate_campaign", new_callable=AsyncMock, return_value=mock_campaign_output),
        patch("app.safety.approval.check_approval_status", new_callable=AsyncMock, return_value=None),
    ):
        from app.agent.nodes.executor import executor_node

        step = {
            "step_number": 1,
            "description": "Generate campaign",
            "tool_name": "generate_campaign",
            "tool_input": {
                "product": "Summer Collection",
                "goal": "drive sales",
                "audience": "customers",
            },
            "requires_approval": False,
        }

        state = AgentState(
            task_id="test-123",
            user_task="Create campaign",
            plan=[step],
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

        result = await executor_node(state)

    assert result["current_step_idx"] == 1
    assert len(result["step_results"]) == 1
    assert result["step_results"][0]["status"] == "success"


# ── Critic node ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_critic_approves_good_output():
    mock_evaluation = {
        "verdict": "approve",
        "score": 9,
        "summary": "Excellent campaign copy",
        "improvements": [],
        "final_output": "Subject: Summer Sale!\n\nDear customer...",
    }

    with patch("app.agent.llm_client.call_llm_json", new_callable=AsyncMock, return_value=mock_evaluation):
        from app.agent.nodes.critic import critic_node

        state = AgentState(
            task_id="test-123",
            user_task="Create summer campaign",
            plan=[],
            current_step_idx=1,
            memory_context="",
            step_results=[{"step_number": 1, "tool_name": "generate_campaign", "status": "success", "output": "...", "error": None}],
            pending_approval=None,
            final_output="Subject: Summer Sale!\n\nDear customer...",
            critique=None,
            revision_count=0,
            status="running",
            errors=[],
        )

        result = await critic_node(state)

    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_critic_requests_revision_when_score_low():
    mock_evaluation = {
        "verdict": "revise",
        "score": 5,
        "summary": "Missing call-to-action",
        "improvements": ["Add a clear CTA button", "Make the subject more urgent"],
        "final_output": "Improved version...",
    }

    with patch("app.agent.llm_client.call_llm_json", new_callable=AsyncMock, return_value=mock_evaluation):
        from app.agent.nodes.critic import critic_node

        state = AgentState(
            task_id="test-123",
            user_task="Create summer campaign",
            plan=[],
            current_step_idx=1,
            memory_context="",
            step_results=[],
            pending_approval=None,
            final_output="Weak output",
            critique=None,
            revision_count=0,
            status="running",
            errors=[],
        )

        result = await critic_node(state)

    # Should request revision and increment counter
    assert result["revision_count"] == 1
    assert result["current_step_idx"] == 0  # Reset for re-run


# ── Graph routing ─────────────────────────────────────────────────────────────

def test_route_after_executor_loops_when_steps_remain():
    from app.agent.graph import route_after_executor

    state = AgentState(
        task_id="t", user_task="t", plan=[{}, {}], current_step_idx=1,
        memory_context="", step_results=[], pending_approval=None,
        final_output="", critique=None, revision_count=0,
        status="running", errors=[],
    )
    assert route_after_executor(state) == "continue"


def test_route_after_executor_sends_to_review_when_done():
    from app.agent.graph import route_after_executor

    state = AgentState(
        task_id="t", user_task="t", plan=[{}], current_step_idx=1,
        memory_context="", step_results=[], pending_approval=None,
        final_output="", critique=None, revision_count=0,
        status="running", errors=[],
    )
    assert route_after_executor(state) == "review"


def test_route_after_executor_ends_on_pending_approval():
    from app.agent.graph import route_after_executor

    state = AgentState(
        task_id="t", user_task="t", plan=[{}], current_step_idx=0,
        memory_context="", step_results=[], pending_approval=None,
        final_output="", critique=None, revision_count=0,
        status="pending_approval", errors=[],
    )
    assert route_after_executor(state) == "end"
