"""Ingestion service: scrape articles by date range, auto-trigger, persist."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_session
from src.core.models import Article
from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Approximate token count: chars / 4."""
    return max(len(text) // 4, 1)


def should_auto_analyze(tags: list[str], keywords: list[str]) -> bool:
    """Return True if any native tag matches any auto-analyze keyword."""
    lower_tags = {t.lower().strip() for t in tags}
    for kw in keywords:
        for tag in lower_tags:
            if kw in tag or tag in kw:
                return True
    return False


def ingest_from_scraper(
    scraper: BaseScraper,
    *,
    since: datetime,
    until: datetime | None = None,
) -> dict:
    """Run a scraper for a date range and persist new articles.

    Returns {"new": int, "skipped": int, "queued": int, "total_fetched": int}.
    """
    raw_articles = scraper.fetch_articles(since=since, until=until)
    keywords = settings.keywords_list

    stats = {"new": 0, "skipped": 0, "queued": 0, "total_fetched": len(raw_articles)}
    session: Session = get_session()

    try:
        for raw in raw_articles:
            _ingest_one(session, raw, keywords, stats)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(
        "Ingestion complete: fetched %d, new %d (queued %d), skipped %d",
        stats["total_fetched"],
        stats["new"],
        stats["queued"],
        stats["skipped"],
    )
    return stats


def _ingest_one(
    session: Session,
    raw: RawArticle,
    keywords: list[str],
    stats: dict,
) -> None:
    tokens = estimate_tokens(raw.raw_text)
    status = (
        "QUEUED_FOR_ANALYSIS"
        if should_auto_analyze(raw.native_tags, keywords)
        else "PENDING"
    )

    stmt = (
        pg_insert(Article)
        .values(
            source=raw.source,
            title=raw.title,
            link=raw.link,
            published_at=raw.published_at,
            raw_text=raw.raw_text,
            native_tags=raw.native_tags,
            estimated_tokens=tokens,
            status=status,
        )
        .on_conflict_do_nothing(index_elements=["link"])
    )
    result = session.execute(stmt)

    if result.rowcount == 0:
        stats["skipped"] += 1
    else:
        stats["new"] += 1
        if status == "QUEUED_FOR_ANALYSIS":
            stats["queued"] += 1


def ingest_all(
    *,
    since: datetime,
    until: datetime | None = None,
) -> dict:
    """Run all registered scrapers for a date range."""
    from src.scrapers.habr import HabrScraper
    from src.scrapers.vc import VcScraper

    total_stats = {"new": 0, "skipped": 0, "queued": 0, "total_fetched": 0}

    for scraper in [HabrScraper(), VcScraper()]:
        try:
            s = ingest_from_scraper(scraper, since=since, until=until)
            for k in total_stats:
                total_stats[k] += s[k]
        except Exception as exc:
            logger.error("Scraper %s failed: %s", type(scraper).__name__, exc)

    return total_stats


def get_db_date_coverage() -> dict:
    """Return min/max published_at dates and per-day counts in DB."""
    session: Session = get_session()
    try:
        row = session.execute(
            select(
                func.min(Article.published_at),
                func.max(Article.published_at),
                func.count(Article.id),
            )
        ).one()
        min_date, max_date, total = row

        # Per-source counts
        source_rows = session.execute(
            select(Article.source, func.count(Article.id)).group_by(Article.source)
        ).all()
        per_source = {src: cnt for src, cnt in source_rows}

        return {
            "min_date": min_date,
            "max_date": max_date,
            "total": total,
            "per_source": per_source,
        }
    finally:
        session.close()
