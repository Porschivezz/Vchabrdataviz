"""Ingestion service: scrape articles, apply auto-trigger logic, persist to DB."""

from __future__ import annotations

import logging

from sqlalchemy import select
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


def ingest_from_scraper(scraper: BaseScraper, limit: int = 20) -> dict:
    """Run a scraper and persist new articles.

    Returns a summary dict: {"new": int, "skipped": int, "queued": int}.
    """
    raw_articles = scraper.fetch_articles(limit=limit)
    keywords = settings.keywords_list

    stats = {"new": 0, "skipped": 0, "queued": 0}
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
        "Ingestion complete: %d new (%d queued), %d skipped",
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
    # Check for duplicate by link
    existing = session.execute(
        select(Article.id).where(Article.link == raw.link)
    ).scalar_one_or_none()

    if existing is not None:
        stats["skipped"] += 1
        return

    tokens = estimate_tokens(raw.raw_text)

    if should_auto_analyze(raw.native_tags, keywords):
        status = "QUEUED_FOR_ANALYSIS"
        stats["queued"] += 1
    else:
        status = "PENDING"

    article = Article(
        source=raw.source,
        title=raw.title,
        link=raw.link,
        published_at=raw.published_at,
        raw_text=raw.raw_text,
        native_tags=raw.native_tags,
        estimated_tokens=tokens,
        status=status,
    )
    session.add(article)
    stats["new"] += 1


def ingest_all(limit_per_source: int = 20) -> dict:
    """Convenience: run all registered scrapers."""
    from src.scrapers.habr import HabrScraper
    from src.scrapers.vc import VcScraper

    total_stats = {"new": 0, "skipped": 0, "queued": 0}

    for scraper in [HabrScraper(), VcScraper()]:
        try:
            s = ingest_from_scraper(scraper, limit=limit_per_source)
            for k in total_stats:
                total_stats[k] += s[k]
        except Exception as exc:
            logger.error("Scraper %s failed: %s", type(scraper).__name__, exc)

    return total_stats
