"""Analysis service: run LLM on articles by date range."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session

from src.core.database import get_session
from src.core.models import Article
from src.nlp.base import BaseLLMProvider

logger = logging.getLogger(__name__)


def analyze_by_date_range(
    provider: BaseLLMProvider,
    *,
    since: datetime,
    until: datetime,
    statuses: list[str] | None = None,
) -> int:
    """Analyze all unprocessed articles within a date range.

    Returns the count of successfully analyzed articles.
    """
    if statuses is None:
        statuses = ["QUEUED_FOR_ANALYSIS", "PENDING"]

    session: Session = get_session()
    analyzed = 0

    try:
        status_conds = [Article.status == s for s in statuses]
        articles = (
            session.execute(
                select(Article)
                .where(
                    and_(
                        or_(*status_conds),
                        Article.published_at >= since,
                        Article.published_at <= until,
                    )
                )
                .order_by(Article.published_at)
            )
            .scalars()
            .all()
        )

        total = len(articles)
        logger.info(
            "Analysis: found %d articles to process in range %s – %s",
            total, since.date(), until.date(),
        )

        for i, article in enumerate(articles):
            try:
                result = provider.summarize_and_extract(
                    article.raw_text, title=article.title
                )
                article.summary = result.summary
                article.entities = result.entities
                if result.embedding and any(v != 0.0 for v in result.embedding):
                    article.embedding = result.embedding
                article.status = "ANALYZED"
                session.commit()
                analyzed += 1

                if (analyzed) % 10 == 0:
                    logger.info("Analysis progress: %d / %d", analyzed, total)

            except Exception as exc:
                session.rollback()
                logger.error(
                    "Failed to analyze article %s: %s", article.id, exc,
                )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info("Analysis complete: %d / %d articles processed", analyzed, total)
    return analyzed
