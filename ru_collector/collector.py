"""Collector job: polls all sources and stores articles in the local DB."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ru_collector.db.engine import SessionLocal
from ru_collector.db.models import Article
from ru_collector.scrapers.sources import ALL_SOURCES

logger = logging.getLogger(__name__)


def collect_all(hours_back: int = 24) -> dict[str, int]:
    """Run all scrapers and store results. Returns {source: count} dict."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    results: dict[str, int] = {}

    for source_name, scraper_cls in ALL_SOURCES.items():
        try:
            scraper = scraper_cls()
            articles = scraper.fetch_articles(since=since)
            stored = _store_articles(articles)
            results[source_name] = stored
            logger.info("Collected %s: %d articles, %d new", source_name, len(articles), stored)
        except Exception:
            logger.exception("Failed to collect %s", source_name)
            results[source_name] = -1

    return results


def collect_source(source_name: str, hours_back: int = 24) -> int:
    """Collect articles from a single source. Returns count of new articles."""
    if source_name not in ALL_SOURCES:
        raise ValueError(f"Unknown source: {source_name}")

    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    scraper = ALL_SOURCES[source_name]()
    articles = scraper.fetch_articles(since=since)
    stored = _store_articles(articles)
    logger.info("Collected %s: %d articles, %d new", source_name, len(articles), stored)
    return stored


def _store_articles(articles) -> int:
    """Insert articles into the DB, skipping duplicates by link. Returns count of new rows."""
    if not articles:
        return 0

    db: Session = SessionLocal()
    new_count = 0
    try:
        for article in articles:
            stmt = pg_insert(Article).values(
                source=article.source,
                title=article.title,
                link=article.link,
                published_at=article.published_at,
                raw_text=article.raw_text,
                tags=article.native_tags,
            ).on_conflict_do_nothing(index_elements=["link"])

            result = db.execute(stmt)
            if result.rowcount > 0:
                new_count += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return new_count
