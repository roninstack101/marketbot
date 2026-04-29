"""
Application configuration loaded from environment variables.
All settings have sensible defaults so the app starts in development
without a fully populated .env file.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_secret_key: str = "dev-secret-key-change-in-production"
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "claudbot"
    postgres_user: str = "claudbot"
    postgres_password: str = "password"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM ───────────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    llm_model: str = "openrouter/anthropic/claude-3.5-sonnet"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_max_retries: int = 3

    # ── LLM model tiers (for routing) ─────────────────────────────────────────
    # Comma-separated lists: first model is primary, rest are fallbacks.
    # Leave empty to fall back to llm_model for all tiers.
    llm_model_strong: str = ""        # e.g. "openrouter/anthropic/claude-opus-4-5,openrouter/openai/gpt-4o"
    llm_model_creative: str = ""      # e.g. "openrouter/anthropic/claude-sonnet-4-5,openrouter/openai/gpt-4o"
    llm_model_fast: str = ""          # e.g. "openrouter/google/gemini-flash-1.5,openrouter/openai/gpt-4o-mini"

    @property
    def llm_model_strong_list(self) -> list[str]:
        return [m.strip() for m in self.llm_model_strong.split(",") if m.strip()]

    @property
    def llm_model_creative_list(self) -> list[str]:
        return [m.strip() for m in self.llm_model_creative.split(",") if m.strip()]

    @property
    def llm_model_fast_list(self) -> list[str]:
        return [m.strip() for m in self.llm_model_fast.split(",") if m.strip()]

    @property
    def llm_model_list(self) -> list[str]:
        return [m.strip() for m in self.llm_model.split(",") if m.strip()]

    # ── LLM Router ────────────────────────────────────────────────────────────
    llm_router_enabled: bool = True   # Enable AI-assisted tier selection
    llm_router_model: str = ""        # Model used for routing decisions (defaults to llm_model_fast)

    # ── NVIDIA NIM ───────────────────────────────────────────────────────────
    nvidia_nim_api_key: str = ""   # Get from build.nvidia.com

    # ── Web search ────────────────────────────────────────────────────────────
    tavily_api_key: str = ""          # Primary search provider (tavily.com)
    serper_api_key: str = ""          # Fallback search provider (serper.dev)

    # ── Document reader ───────────────────────────────────────────────────────
    upload_dir: str = "./uploads"     # Where users place files for read_document

    # ── Image generation ──────────────────────────────────────────────────────
    openai_api_key: str = ""          # Required for generate_image (DALL-E 3)
    image_output_dir: str = "./output/images"

    # ── Web builder ───────────────────────────────────────────────────────────
    web_output_dir: str = "./output/websites"

    # ── Email ─────────────────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    # ── Safety ────────────────────────────────────────────────────────────────
    approval_required_tools: str = "send_email,delete_data,bulk_update"

    @property
    def approval_required_tool_list(self) -> List[str]:
        return [t.strip() for t in self.approval_required_tools.split(",")]

    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""       # From @BotFather on Telegram
    bot_api_base_url: str = "http://localhost:8000"  # ClaudBot FastAPI URL

    # ── Celery ────────────────────────────────────────────────────────────────
    celery_concurrency: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
