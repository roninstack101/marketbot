"""
ClaudBot – FastAPI application entry point.

Startup flow:
  1. Configure structured logging
  2. Create DB tables if they don't exist
  3. Mount all API routers
  4. Expose /health and /docs
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approvals import router as approvals_router
from app.api.brands import router as brands_router
from app.api.chat import router as chat_router
from app.api.history import router as history_router
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.database import async_engine
from app.database import Base
from app.logging_config import configure_logging
from app.models import Task, Approval, Memory, BrandVoice  # ensure models are registered

settings = get_settings()
configure_logging(settings.log_level)
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (idempotent)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("database_ready")
    yield
    await async_engine.dispose()
    log.info("database_disconnected")


app = FastAPI(
    title="ClaudBot",
    description="AI agent system for marketing automation and internal workflows",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow local frontend / dashboard to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(brands_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "1.0.0", "env": settings.app_env}


@app.get("/", tags=["System"])
async def root():
    return {
        "name": "ClaudBot",
        "docs": "/docs",
        "health": "/health",
    }
