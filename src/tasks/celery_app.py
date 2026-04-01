"""Celery application configuration."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.core.config import settings

app = Celery(
    "pulse_runeta",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Beat schedule for periodic tasks
app.conf.beat_schedule = {
    "poll-all-sources-every-30min": {
        "task": "src.tasks.jobs.poll_all_sources",
        "schedule": crontab(minute="*/30"),
    },
    "auto-analyze-queued-every-15min": {
        "task": "src.tasks.jobs.auto_analyze_queued",
        "schedule": crontab(minute="*/15"),
    },
    "generate-daily-digest-at-6am": {
        "task": "src.tasks.jobs.generate_daily_digest",
        "schedule": crontab(hour=6, minute=0),
    },
}

# Autodiscover tasks
app.autodiscover_tasks(["src.tasks"])
