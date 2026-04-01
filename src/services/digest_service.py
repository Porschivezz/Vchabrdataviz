"""Daily digest service — narrative summary with clustering."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from src.core.database import get_session
from src.core.models import Article, DailyDigest

logger = logging.getLogger(__name__)

DIGEST_SYSTEM_PROMPT = """\
You are a tech analyst writing a daily briefing for a Russian-speaking audience.
Given a list of article summaries from today's publications, produce a cohesive narrative digest.

Structure:
1. "Главное за день" — 2-3 sentence overview of the most significant stories.
2. "Ключевые темы" — 3-5 bullet points grouping related stories into themes.
3. "Слабые сигналы" — 1-2 emerging trends worth watching.

Write in Russian. Be concise and analytical. Return plain text (no JSON, no markdown fences)."""


def build_daily_digest(target_date: date) -> dict:
    """Build a narrative digest for the given date.

    Returns {"date": str, "narrative": str, "article_count": int, "avg_sentiment": float|None}.
    """
    session: Session = get_session()

    try:
        since = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        until = since + timedelta(days=1)

        articles = (
            session.execute(
                select(Article)
                .where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= since,
                        Article.published_at < until,
                    )
                )
                .order_by(Article.published_at)
            )
            .scalars()
            .all()
        )

        if not articles:
            logger.info("No analyzed articles for %s, skipping digest", target_date)
            return {"date": str(target_date), "narrative": "", "article_count": 0, "avg_sentiment": None}

        # Compute aggregate stats
        sentiments = [a.sentiment for a in articles if a.sentiment is not None]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None

        # Collect top entities
        entity_counts: dict[str, int] = {}
        for a in articles:
            if a.entities and isinstance(a.entities, dict):
                for category, items in a.entities.items():
                    if isinstance(items, list):
                        for item in items:
                            entity_counts[item] = entity_counts.get(item, 0) + 1
        top_entities = dict(sorted(entity_counts.items(), key=lambda x: -x[1])[:20])

        # Build summaries for LLM
        summaries_text = "\n".join(
            f"- [{a.source.upper()}] {a.title}: {(a.summary or '')[:200]}"
            for a in articles[:100]  # limit to avoid token overflow
        )

        user_msg = (
            f"Дата: {target_date}\n"
            f"Количество статей: {len(articles)}\n"
            f"Средний сентимент: {avg_sentiment:.2f}\n\n"
            f"Статьи:\n{summaries_text}"
        ) if avg_sentiment is not None else (
            f"Дата: {target_date}\n"
            f"Количество статей: {len(articles)}\n\n"
            f"Статьи:\n{summaries_text}"
        )

        # Generate narrative via LLM
        from src.nlp.openrouter import OpenRouterProvider
        provider = OpenRouterProvider()

        try:
            narrative = provider._llm_completion(
                messages=[
                    {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.4,
                max_tokens=2048,
            )
        except Exception as exc:
            logger.error("Digest LLM call failed: %s", exc)
            narrative = f"[Ошибка генерации дайджеста: {exc}]"

        # Persist digest
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = (
            pg_insert(DailyDigest)
            .values(
                digest_date=since,
                source="all",
                narrative=narrative,
                top_entities=top_entities,
                avg_sentiment=avg_sentiment,
                article_count=len(articles),
            )
            .on_conflict_do_update(
                constraint="uq_digest_date_source",
                set_={
                    "narrative": narrative,
                    "top_entities": top_entities,
                    "avg_sentiment": avg_sentiment,
                    "article_count": len(articles),
                },
            )
        )
        session.execute(stmt)
        session.commit()

        logger.info("Digest for %s: %d articles, sentiment=%.2f",
                     target_date, len(articles), avg_sentiment or 0)

        return {
            "date": str(target_date),
            "narrative": narrative,
            "article_count": len(articles),
            "avg_sentiment": avg_sentiment,
        }

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
