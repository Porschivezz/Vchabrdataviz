"""Polarization & Drama Detector — find topics with maximum sentiment divergence."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from src.core.database import get_session
from src.core.models import Article

logger = logging.getLogger(__name__)


def detect_polarized_topics(
    *,
    days: int = 3,
    min_articles: int = 3,
    top_n: int = 15,
) -> list[dict]:
    """Find topics/entities with maximum sentiment divergence across sources.

    Returns sorted by divergence score:
    [{
        "entity": str,
        "sources": {source: {"avg_sentiment": float, "count": int, "titles": [str]}},
        "divergence": float,  # max abs diff between sources
        "overall_hype": float,
        "article_count": int,
    }]
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
                        Article.sentiment.isnot(None),
                    )
                )
            ).scalars().all()
        )

        # entity -> source -> list of (sentiment, hype, title)
        entity_source_data: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            all_entities = set()
            for cat, items in a.entities.items():
                if isinstance(items, list):
                    for item in items:
                        all_entities.add(item)

            for entity in all_entities:
                entity_source_data[entity][a.source].append({
                    "sentiment": a.sentiment,
                    "hype": a.hype_score or 0.0,
                    "title": a.title[:80],
                })

        results = []
        for entity, source_map in entity_source_data.items():
            total_count = sum(len(v) for v in source_map.values())
            if total_count < min_articles:
                continue

            source_stats = {}
            for source, entries in source_map.items():
                sents = [e["sentiment"] for e in entries]
                source_stats[source] = {
                    "avg_sentiment": round(sum(sents) / len(sents), 3),
                    "count": len(entries),
                    "titles": [e["title"] for e in entries[:3]],
                }

            # Compute divergence: max diff between any two sources
            all_avgs = [s["avg_sentiment"] for s in source_stats.values()]
            if len(all_avgs) >= 2:
                divergence = max(all_avgs) - min(all_avgs)
            else:
                divergence = 0.0

            # Overall hype
            all_hypes = [e["hype"] for entries in source_map.values() for e in entries]
            avg_hype = sum(all_hypes) / len(all_hypes) if all_hypes else 0.0

            results.append({
                "entity": entity,
                "sources": source_stats,
                "divergence": round(divergence, 3),
                "overall_hype": round(avg_hype, 2),
                "article_count": total_count,
            })

        results.sort(key=lambda x: -x["divergence"])
        return results[:top_n]

    finally:
        session.close()


def detect_chain_reactions(
    *,
    days: int = 3,
    min_articles: int = 5,
    top_n: int = 10,
) -> list[dict]:
    """Detect topics that spread across sources over time (chain reactions).

    Returns [{
        "entity": str,
        "timeline": [{"hour": str, "source": str, "title": str, "sentiment": float}],
        "sources_reached": int,
        "peak_hype": float,
        "total_articles": int,
    }]
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
                        Article.published_at.isnot(None),
                    )
                )
                .order_by(Article.published_at)
            ).scalars().all()
        )

        # entity -> list of (datetime, source, title, sentiment, hype)
        entity_timeline: dict[str, list] = defaultdict(list)

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            all_entities = set()
            for cat, items in a.entities.items():
                if isinstance(items, list):
                    for item in items:
                        all_entities.add(item)

            for entity in all_entities:
                entity_timeline[entity].append({
                    "datetime": a.published_at,
                    "hour": a.published_at.strftime("%Y-%m-%d %H:00"),
                    "source": a.source,
                    "title": a.title[:80],
                    "sentiment": a.sentiment or 0.0,
                    "hype": a.hype_score or 0.0,
                })

        results = []
        for entity, timeline in entity_timeline.items():
            if len(timeline) < min_articles:
                continue

            sources = set(t["source"] for t in timeline)
            peak_hype = max(t["hype"] for t in timeline)

            results.append({
                "entity": entity,
                "timeline": timeline,
                "sources_reached": len(sources),
                "peak_hype": round(peak_hype, 2),
                "total_articles": len(timeline),
                "first_seen": timeline[0]["datetime"].isoformat() if timeline else "",
            })

        # Sort by article count * sources (virality proxy)
        results.sort(key=lambda x: -(x["total_articles"] * x["sources_reached"]))
        return results[:top_n]

    finally:
        session.close()


def get_drama_topics(*, days: int = 3, top_n: int = 10) -> list[dict]:
    """Get topics with highest hype_score — maximum drama/controversy."""
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.published_at >= since,
                        Article.hype_score.isnot(None),
                    )
                )
                .order_by(Article.hype_score.desc())
                .limit(top_n * 3)
            ).scalars().all()
        )

        # Group by entity to find the most drama-generating entities
        entity_hype: dict[str, list] = defaultdict(list)

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            all_entities = set()
            for cat, items in a.entities.items():
                if isinstance(items, list):
                    for item in items:
                        all_entities.add(item)
            for entity in all_entities:
                entity_hype[entity].append({
                    "title": a.title[:80],
                    "source": a.source,
                    "hype_score": a.hype_score,
                    "sentiment": a.sentiment,
                    "link": a.link,
                })

        results = []
        for entity, articles_data in entity_hype.items():
            if len(articles_data) < 2:
                continue
            avg_hype = sum(a["hype_score"] for a in articles_data) / len(articles_data)
            results.append({
                "entity": entity,
                "avg_hype": round(avg_hype, 2),
                "article_count": len(articles_data),
                "top_articles": sorted(articles_data, key=lambda x: -x["hype_score"])[:5],
            })

        results.sort(key=lambda x: -x["avg_hype"])
        return results[:top_n]

    finally:
        session.close()
