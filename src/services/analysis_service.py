"""Analysis service: run LLM on queued/pending articles."""

from __future__ import annotations

import logging

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.core.database import get_session
from src.core.models import Article
from src.nlp.base import BaseLLMProvider

logger = logging.getLogger(__name__)


def analyze_articles(
    provider: BaseLLMProvider,
    *,
    statuses: list[str] | None = None,
    batch_size: int = 10,
) -> int:
    """Analyze articles matching the given statuses.

    Returns the count of successfully analyzed articles.
    """
    if statuses is None:
        statuses = ["QUEUED_FOR_ANALYSIS"]

    session: Session = get_session()
    analyzed = 0

    try:
        conditions = [Article.status == s for s in statuses]
        articles = (
            session.execute(
                select(Article)
                .where(or_(*conditions))
                .order_by(Article.created_at)
                .limit(batch_size)
            )
            .scalars()
            .all()
        )

        logger.info("Analysis: found %d articles to process", len(articles))

        for article in articles:
            try:
                result = provider.summarize_and_extract(
                    article.raw_text, title=article.title
                )
                article.summary = result.summary
                article.entities = result.entities
                if result.embedding and any(v != 0.0 for v in result.embedding):
                    article.embedding = result.embedding
                article.status = "ANALYZED"
                analyzed += 1
                logger.info("Analyzed: %s", article.title[:60])
            except Exception as exc:
                logger.error(
                    "Failed to analyze article %s: %s", article.id, exc
                )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info("Analysis complete: %d articles processed", analyzed)
    return analyzed


def analyze_queued(provider: BaseLLMProvider, batch_size: int = 10) -> int:
    """Analyze only QUEUED_FOR_ANALYSIS articles."""
    return analyze_articles(provider, statuses=["QUEUED_FOR_ANALYSIS"], batch_size=batch_size)


def analyze_pending(provider: BaseLLMProvider, batch_size: int = 10) -> int:
    """Force-analyze PENDING articles (admin action)."""
    return analyze_articles(provider, statuses=["PENDING"], batch_size=batch_size)


def analyze_all_unprocessed(provider: BaseLLMProvider, batch_size: int = 10) -> int:
    """Analyze both QUEUED and PENDING articles."""
    return analyze_articles(
        provider,
        statuses=["QUEUED_FOR_ANALYSIS", "PENDING"],
        batch_size=batch_size,
    )
