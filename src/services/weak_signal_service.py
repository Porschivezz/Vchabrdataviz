"""Weak Signal Tracker — sonar-style detection with LLM forecasting."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from src.core.database import get_session
from src.core.models import Article

logger = logging.getLogger(__name__)


def detect_weak_signals(
    *,
    days: int = 30,
    max_mentions: int = 10,
    min_mentions: int = 2,
) -> list[dict]:
    """Detect weak signals — entities with low mention count but high hype context.

    Returns [{
        "signal": str,
        "mentions": int,
        "avg_hype": float,
        "avg_sentiment": float,
        "first_seen": str,
        "sources": list[str],
        "context_articles": [{title, source, link, summary}],
        "recency_score": float,  # 0-1, how recent the signal is
    }]
    """
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        now = datetime.now(timezone.utc)

        articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= since,
                    )
                )
                .order_by(Article.published_at)
            ).scalars().all()
        )

        # Collect weak_signals specifically
        signal_data: dict[str, list] = defaultdict(list)

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            weak_signals = a.entities.get("weak_signals", [])
            if not isinstance(weak_signals, list):
                continue
            for signal in weak_signals:
                signal_data[signal].append({
                    "title": a.title[:100],
                    "source": a.source,
                    "link": a.link,
                    "summary": (a.summary or "")[:200],
                    "sentiment": a.sentiment or 0.0,
                    "hype": a.hype_score or 0.0,
                    "published_at": a.published_at,
                })

        results = []
        for signal, entries in signal_data.items():
            count = len(entries)
            if count < min_mentions or count > max_mentions:
                continue

            avg_hype = sum(e["hype"] for e in entries) / count
            avg_sent = sum(e["sentiment"] for e in entries) / count
            sources = list(set(e["source"] for e in entries))
            first_seen = min(e["published_at"] for e in entries if e["published_at"])
            last_seen = max(e["published_at"] for e in entries if e["published_at"])

            # Recency: how close is the last mention to now (0=old, 1=very recent)
            total_span = (now - since).total_seconds()
            if total_span > 0:
                recency = (last_seen - since).total_seconds() / total_span
            else:
                recency = 0.5

            results.append({
                "signal": signal,
                "mentions": count,
                "avg_hype": round(avg_hype, 2),
                "avg_sentiment": round(avg_sent, 2),
                "first_seen": first_seen.strftime("%Y-%m-%d") if first_seen else "",
                "last_seen": last_seen.strftime("%Y-%m-%d") if last_seen else "",
                "sources": sources,
                "context_articles": entries[:5],
                "recency_score": round(recency, 2),
            })

        # Sort by: recency * hype (most recent + most hyped = strongest signal)
        results.sort(key=lambda x: -(x["recency_score"] * x["avg_hype"] * x["mentions"]))
        return results

    finally:
        session.close()


def generate_signal_forecast(signal_name: str, context_summaries: list[str]) -> str:
    """Use LLM to generate a forecast hypothesis for a weak signal.

    Returns a narrative forecast string.
    """
    from src.nlp.openrouter import OpenRouterProvider

    provider = OpenRouterProvider()

    forecast_prompt = f"""\
Ты — футуролог-аналитик. Тебе дан "слабый сигнал" — зарождающийся тренд, \
который пока упоминается редко, но может стать значимым.

Слабый сигнал: "{signal_name}"

Контекст из статей:
{chr(10).join(f'- {s}' for s in context_summaries[:5])}

Сгенерируй краткий прогноз (3-5 предложений) на русском языке:
1. Почему этот сигнал может стать важным трендом.
2. Какие отрасли/компании будут затронуты.
3. Временной горизонт: когда это может стать мейнстримом.
Будь конкретен. Не отделывайся общими фразами."""

    try:
        return provider._llm_completion(
            messages=[
                {"role": "user", "content": forecast_prompt},
            ],
            temperature=0.6,
            max_tokens=512,
        )
    except Exception as exc:
        logger.error("Forecast generation failed: %s", exc)
        return f"[Ошибка генерации прогноза: {exc}]"
