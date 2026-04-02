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

# Beat schedule: staggered polling every 5 minutes
app.conf.beat_schedule = {
    # Minute 0,15,30,45: poll all sources (staggered internally)
    "poll-all-sources-every-15min": {
        "task": "src.tasks.jobs.poll_all_sources",
        "schedule": crontab(minute="*/15"),
    },
    # Minute 5,20,35,50: auto-analyze queued articles
    "auto-analyze-queued": {
        "task": "src.tasks.jobs.auto_analyze_queued",
        "schedule": crontab(minute="5,20,35,50"),
    },
    # Daily digest at 6:00 AM UTC
    "generate-daily-digest-at-6am": {
        "task": "src.tasks.jobs.generate_daily_digest",
        "schedule": crontab(hour=6, minute=0),
    },
}

# Autodiscover tasks
app.autodiscover_tasks(["src.tasks"])

# Explicitly import tasks module so Celery registers all task functions
import src.tasks.jobs  # noqa: F401
