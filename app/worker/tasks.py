"""
Celery tasks that run the LangGraph agent in background workers.

execute_task       – runs a new task from scratch
resume_task        – resumes a task after an approval decision
"""
import asyncio
import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import update

from app.database import get_sync_db
from app.logging_config import configure_logging
from app.memory.store import save_task_memory_sync
from app.models.task import Task
from app.worker.celery_app import celery_app

configure_logging()
log = structlog.get_logger(__name__)


def _update_task_sync(task_id: str, updates: dict) -> None:
    """Helper: apply a dict of column updates to a Task row."""
    with get_sync_db() as session:
        session.execute(
            update(Task).where(Task.id == task_id).values(**updates)
        )


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    name="claudbot.execute_task",
)
def execute_task(self, task_id: str, user_task: str, created_by: str | None = None, user_id: str = ""):
    """
    Entry point for all new tasks.
    Runs the LangGraph graph and writes results back to the DB.
    """
    log.info("worker_task_start", task_id=task_id, celery_task=self.request.id)

    # Mark as running
    _update_task_sync(task_id, {"status": "running"})

    try:
        from app.agent.graph import run_agent

        # Run the async graph in this sync Celery worker context
        final_state = asyncio.run(run_agent(task_id=task_id, user_task=user_task))

    except Exception as exc:
        log.error("worker_task_error", task_id=task_id, error=str(exc), exc_info=True)

        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            _update_task_sync(
                task_id,
                {"status": "failed", "error": str(exc)},
            )
        return

    # Persist the full state so it can be resumed if needed
    status = final_state.get("status", "complete")

    updates = {
        "status": status,
        "plan": json.dumps(final_state.get("plan", [])),
        "step_results": json.dumps(final_state.get("step_results", [])),
        "final_output": final_state.get("final_output", ""),
        "critique": final_state.get("critique"),
        "error": "; ".join(final_state.get("errors", [])) or None,
        # Serialise full state for potential resumption
        "agent_state": json.dumps(
            {k: v for k, v in final_state.items() if k != "step_results"}
        ),
    }
    _update_task_sync(task_id, updates)

    # Save to memory only on successful completion
    if status == "complete" and final_state.get("final_output"):
        try:
            save_task_memory_sync(
                task_id=task_id,
                user_task=user_task,
                final_output=final_state["final_output"],
            )
        except Exception as mem_exc:
            log.warning("memory_save_failed", task_id=task_id, error=str(mem_exc))

    log.info("worker_task_done", task_id=task_id, status=status)


@celery_app.task(
    bind=True,
    max_retries=1,
    name="claudbot.resume_task",
)
def resume_task(self, task_id: str, approved_by: str):
    """
    Resume execution of a task that was paused waiting for approval.
    Loads the saved agent state from the DB and re-runs the graph.
    """
    log.info("worker_resume_start", task_id=task_id, approved_by=approved_by)

    # Load saved state from DB
    with get_sync_db() as session:
        task = session.get(Task, task_id)
        if not task:
            log.error("resume_task_not_found", task_id=task_id)
            return

        if not task.agent_state:
            log.error("resume_no_state", task_id=task_id)
            _update_task_sync(task_id, {"status": "failed", "error": "No saved state to resume from"})
            return

        saved_state = json.loads(task.agent_state) if isinstance(task.agent_state, str) else task.agent_state
        saved_state["step_results"] = json.loads(task.step_results) if isinstance(task.step_results, str) else (task.step_results or [])
        user_task = task.user_task

    _update_task_sync(task_id, {"status": "running"})

    try:
        from app.agent.graph import run_agent

        final_state = asyncio.run(
            run_agent(task_id=task_id, user_task=user_task, existing_state=saved_state)
        )
    except Exception as exc:
        log.error("resume_task_error", task_id=task_id, error=str(exc), exc_info=True)
        _update_task_sync(task_id, {"status": "failed", "error": str(exc)})
        return

    status = final_state.get("status", "complete")
    updates = {
        "status": status,
        "step_results": json.dumps(final_state.get("step_results", [])),
        "final_output": final_state.get("final_output", ""),
        "critique": final_state.get("critique"),
        "error": "; ".join(final_state.get("errors", [])) or None,
        "agent_state": json.dumps(
            {k: v for k, v in final_state.items() if k != "step_results"}
        ),
    }
    _update_task_sync(task_id, updates)

    if status == "complete" and final_state.get("final_output"):
        try:
            save_task_memory_sync(task_id, user_task, final_state["final_output"])
        except Exception:
            pass

    log.info("worker_resume_done", task_id=task_id, status=status)
