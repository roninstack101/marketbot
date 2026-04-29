"""
Thin async HTTP client that talks to the ClaudBot FastAPI server.
"""
import httpx
from app.config import get_settings

settings = get_settings()
_BASE = settings.bot_api_base_url.rstrip("/")


async def submit_task(user_task: str, created_by: str = "telegram") -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_BASE}/tasks",
            json={"user_task": user_task, "created_by": created_by},
        )
        r.raise_for_status()
        return r.json()["id"]


async def get_task(task_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{_BASE}/tasks/{task_id}")
        r.raise_for_status()
        return r.json()


async def respond_to_task(task_id: str, answer: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_BASE}/tasks/{task_id}/respond",
            json={"answer": answer},
        )
        r.raise_for_status()


async def approve(approval_id: str, approved_by: str = "telegram_user") -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_BASE}/approvals/{approval_id}/approve",
            json={"approved_by": approved_by},
        )
        r.raise_for_status()


async def reject(approval_id: str, approved_by: str = "telegram_user") -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_BASE}/approvals/{approval_id}/reject",
            json={"approved_by": approved_by, "rejection_reason": "Rejected via Telegram"},
        )
        r.raise_for_status()
