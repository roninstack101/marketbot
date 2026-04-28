"""
Celery application factory.
"""
from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "claudbot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Concurrency is set via CLI flag (--concurrency) or CELERY_CONCURRENCY env
    worker_concurrency=settings.celery_concurrency,
    # Result expiry: keep results for 24h
    result_expires=86400,
    # Retry policy for broker connection
    broker_connection_retry_on_startup=True,
)
