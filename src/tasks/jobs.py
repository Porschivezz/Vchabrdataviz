"""Celery tasks for ingestion, analysis, and digest generation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="src.tasks.jobs.poll_all_sources", bind=True, max_retries=2)
def poll_all_sources(self) -> dict:
    """Poll all enabled sources for recent articles (last 2 hours)."""
    from src.services.ingestion_service import ingest_all

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=2)

    try:
        stats = ingest_all(since=since, until=now)
        logger.info("Poll complete: %s", stats)
        return stats
    except Exception as exc:
        logger.error("Poll failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(name="src.tasks.jobs.ingest_source", bind=True, max_retries=2)
def ingest_source(self, source_name: str, since_iso: str, until_iso: str) -> dict:
    """Ingest a specific source for a date range."""
    from src.services.ingestion_service import ingest_all

    since = datetime.fromisoformat(since_iso)
    until = datetime.fromisoformat(until_iso)

    try:
        return ingest_all(since=since, until=until, sources=[source_name])
    except Exception as exc:
        logger.error("Ingest %s failed: %s", source_name, exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(name="src.tasks.jobs.ingest_all_sources", bind=True, max_retries=2)
def ingest_all_sources(self, since_iso: str, until_iso: str) -> dict:
    """Ingest all enabled sources for a date range."""
    from src.services.ingestion_service import ingest_all

    since = datetime.fromisoformat(since_iso)
    until = datetime.fromisoformat(until_iso)

    try:
        return ingest_all(since=since, until=until)
    except Exception as exc:
        logger.error("Ingest all failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


@app.task(name="src.tasks.jobs.analyze_date_range", bind=True, max_retries=1)
def analyze_date_range(
    self, since_iso: str, until_iso: str, statuses: list[str] | None = None
) -> int:
    """Analyze articles in a date range."""
    from src.nlp.openrouter import OpenRouterProvider
    from src.services.analysis_service import analyze_by_date_range

    since = datetime.fromisoformat(since_iso)
    until = datetime.fromisoformat(until_iso)

    try:
        provider = OpenRouterProvider()
        return analyze_by_date_range(provider, since=since, until=until, statuses=statuses)
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


@app.task(name="src.tasks.jobs.auto_analyze_queued")
def auto_analyze_queued() -> int:
    """Auto-analyze all queued articles from the last 48 hours."""
    from src.nlp.openrouter import OpenRouterProvider
    from src.services.analysis_service import analyze_by_date_range

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=48)

    provider = OpenRouterProvider()
    return analyze_by_date_range(
        provider,
        since=since,
        until=now,
        statuses=["QUEUED_FOR_ANALYSIS"],
    )


@app.task(name="src.tasks.jobs.generate_daily_digest")
def generate_daily_digest(target_date_iso: str | None = None) -> dict:
    """Generate daily digest for yesterday (or specified date)."""
    from src.services.digest_service import build_daily_digest

    if target_date_iso:
        target = datetime.fromisoformat(target_date_iso).date()
    else:
        target = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    return build_daily_digest(target)
