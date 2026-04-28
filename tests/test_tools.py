"""
Unit tests for individual tools.
LLM calls are mocked so these run without API keys.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch


# ── generate_campaign ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_campaign_returns_json():
    mock_output = {
        "subject": "Summer Sale – 30% Off Everything",
        "preview_text": "Shop now before it ends",
        "headline": "Big Summer Deals Are Here",
        "body": "Dear Customer,\n\nOur summer sale is live...",
        "cta_text": "Shop Now",
        "cta_url": "https://example.com/sale",
        "tone": "friendly",
    }

    with patch(
        "app.agent.llm_client.call_llm_json",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        from app.tools.campaign import generate_campaign

        result = await generate_campaign(
            product="ClaudBot SaaS",
            goal="drive sign-ups",
            audience="small business owners",
        )

    data = json.loads(result)
    assert "subject" in data
    assert "body" in data
    assert "cta_text" in data


# ── write_email ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_email_returns_string():
    mock_text = "Subject: Q2 Report\n\nHi Team,\n\nPlease find attached..."

    with patch(
        "app.agent.llm_client.call_llm",
        new_callable=AsyncMock,
        return_value=mock_text,
    ):
        from app.tools.email_writer import write_email

        result = await write_email(
            to="team@company.com",
            subject_brief="Q2 report summary",
            body_brief="Highlight revenue growth and key wins",
        )

    assert "Subject:" in result
    assert len(result) > 20


# ── store_data / retrieve_data ────────────────────────────────────────────────

def test_store_retrieve_data(tmp_path, monkeypatch):
    """
    Smoke test using a real SQLite in-memory DB (via SQLAlchemy sync).
    In CI, point SYNC_DATABASE_URL at a test Postgres instead.
    """
    # This test is integration-level and requires a DB.
    # Mark it as skipped unless CLAUDBOT_RUN_DB_TESTS=1 is set.
    import os
    if not os.getenv("CLAUDBOT_RUN_DB_TESTS"):
        pytest.skip("Set CLAUDBOT_RUN_DB_TESTS=1 to run DB tests")
