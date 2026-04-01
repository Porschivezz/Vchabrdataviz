"""Hybrid search: combines vector similarity with full-text search."""

from __future__ import annotations

import logging

from sqlalchemy import text

from src.core.database import get_session

logger = logging.getLogger(__name__)


def hybrid_search(
    query_text: str,
    query_embedding: list[float],
    *,
    top_k: int = 20,
    vector_weight: float = 0.6,
    fts_weight: float = 0.4,
) -> list[dict]:
    """Perform hybrid search combining cosine similarity and PostgreSQL FTS.

    Returns ranked results with combined score.
    """
    session = get_session()
    try:
        vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

        results = session.execute(
            text("""
                WITH vector_results AS (
                    SELECT id, title, source, summary, link, published_at,
                           entities, sentiment,
                           1 - (embedding <=> :vec ::vector) AS vec_score
                    FROM articles
                    WHERE status = 'ANALYZED' AND embedding IS NOT NULL
                    ORDER BY embedding <=> :vec ::vector
                    LIMIT :candidate_limit
                ),
                fts_results AS (
                    SELECT id,
                           ts_rank(
                               to_tsvector('russian', coalesce(title,'') || ' ' || coalesce(summary,'')),
                               plainto_tsquery('russian', :query)
                           ) AS fts_score
                    FROM articles
                    WHERE status = 'ANALYZED'
                      AND to_tsvector('russian', coalesce(title,'') || ' ' || coalesce(summary,''))
                          @@ plainto_tsquery('russian', :query)
                )
                SELECT
                    v.id, v.title, v.source, v.summary, v.link, v.published_at,
                    v.entities, v.sentiment, v.vec_score,
                    COALESCE(f.fts_score, 0) AS fts_score,
                    (:vec_w * v.vec_score + :fts_w * COALESCE(f.fts_score, 0)) AS combined_score
                FROM vector_results v
                LEFT JOIN fts_results f ON v.id = f.id
                ORDER BY combined_score DESC
                LIMIT :k
            """),
            {
                "vec": vec_literal,
                "query": query_text,
                "candidate_limit": top_k * 3,
                "k": top_k,
                "vec_w": vector_weight,
                "fts_w": fts_weight,
            },
        ).fetchall()

        return [
            {
                "id": str(r.id),
                "title": r.title,
                "source": r.source,
                "summary": r.summary,
                "link": r.link,
                "published_at": r.published_at,
                "entities": r.entities,
                "sentiment": r.sentiment,
                "vec_score": round(float(r.vec_score), 4),
                "fts_score": round(float(r.fts_score), 4),
                "combined_score": round(float(r.combined_score), 4),
            }
            for r in results
        ]
    except Exception as exc:
        logger.error("Hybrid search failed: %s", exc)
        return []
    finally:
        session.close()
