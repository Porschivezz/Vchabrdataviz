"""Trend velocity service — detect entities accelerating in mentions."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, and_

from src.core.database import get_session
from src.core.models import Article

logger = logging.getLogger(__name__)


def compute_trend_velocity(
    *,
    window_days: int = 7,
    compare_days: int = 7,
    min_mentions: int = 3,
) -> list[dict]:
    """Compute entity mention velocity: current window vs previous window.

    Returns sorted list of entities with velocity score:
    [{"entity": str, "category": str, "current": int, "previous": int, "velocity": float}]
    """
    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        current_start = now - timedelta(days=window_days)
        prev_start = current_start - timedelta(days=compare_days)

        # Fetch articles in both windows
        current_articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= current_start,
                        Article.published_at <= now,
                    )
                )
            ).scalars().all()
        )

        prev_articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= prev_start,
                        Article.published_at < current_start,
                    )
                )
            ).scalars().all()
        )

        def count_entities(articles: list) -> dict[tuple[str, str], int]:
            counts: dict[tuple[str, str], int] = defaultdict(int)
            for a in articles:
                if not a.entities or not isinstance(a.entities, dict):
                    continue
                for cat, items in a.entities.items():
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        counts[(item, cat)] += 1
            return counts

        current_counts = count_entities(current_articles)
        prev_counts = count_entities(prev_articles)

        # Compute velocity
        results = []
        all_keys = set(current_counts.keys()) | set(prev_counts.keys())

        for entity, category in all_keys:
            curr = current_counts.get((entity, category), 0)
            prev = prev_counts.get((entity, category), 0)

            if curr < min_mentions:
                continue

            # Velocity: relative change, smoothed to avoid division by zero
            velocity = (curr - prev) / max(prev, 1)
            results.append({
                "entity": entity,
                "category": category,
                "current": curr,
                "previous": prev,
                "velocity": round(velocity, 2),
            })

        # Sort by velocity descending
        results.sort(key=lambda x: -x["velocity"])
        return results

    finally:
        session.close()


def get_entity_timeline(
    entity_name: str,
    *,
    days: int = 30,
) -> list[dict]:
    """Get daily mention count for a specific entity.

    Returns [{"date": str, "count": int}].
    """
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= since,
                    )
                )
            ).scalars().all()
        )

        daily_counts: dict[str, int] = defaultdict(int)
        name_lower = entity_name.lower()

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            for cat, items in a.entities.items():
                if isinstance(items, list):
                    for item in items:
                        if item.lower() == name_lower:
                            day_key = a.published_at.strftime("%Y-%m-%d") if a.published_at else "unknown"
                            daily_counts[day_key] += 1

        return [
            {"date": d, "count": c}
            for d, c in sorted(daily_counts.items())
        ]

    finally:
        session.close()
