"""Celery application factory for SpecForge background workers."""

from celery import Celery
from celery.schedules import crontab

from src.core.config import get_config

_cfg = get_config()

celery_app = Celery(
    "specforge",
    broker=str(_cfg.redis_url),
    backend=str(_cfg.redis_url),
    include=["src.tasks.execution_tasks"],
)

# Serialization
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,  # 24 hours
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Task routing — all execution tasks go to "executions" queue
celery_app.conf.task_routes = {
    "specforge.execute_template": {"queue": "executions"},
}

# Celery Beat — cleanup expired runs every hour
celery_app.conf.beat_schedule = {
    "cleanup-expired-runs": {
        "task": "specforge.cleanup_expired_runs",
        "schedule": crontab(minute=0),  # hourly
    },
}
