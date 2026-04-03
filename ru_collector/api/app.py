"""FastAPI application — REST API for the EU app to pull collected articles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ru_collector.config import settings
from ru_collector.db.engine import get_db
from ru_collector.db.models import Article

logger = logging.getLogger(__name__)

app = FastAPI(
    title="RU News Collector API",
    description="Serves collected Russian news articles to the main EU app",
    version="1.0.0",
)


def _verify_token(authorization: Annotated[str, Header()] = "") -> None:
    """Simple bearer token auth."""
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/articles/pending")
def get_pending_articles(
    limit: int = Query(default=500, le=5000),
    _: None = Depends(_verify_token),
    db: Session = Depends(get_db),
):
    """Return articles not yet synced to the EU app.

    The EU app calls this endpoint, ingests the articles, then calls
    POST /api/articles/ack to mark them as synced.
    """
    rows = (
        db.query(Article)
        .filter(Article.synced == False)  # noqa: E712
        .order_by(Article.collected_at.asc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "articles": [r.to_dict() for r in rows],
    }


@app.post("/api/articles/ack")
def ack_articles(
    payload: dict,
    _: None = Depends(_verify_token),
    db: Session = Depends(get_db),
):
    """Mark articles as synced after the EU app has ingested them.

    Expects: {"ids": [1, 2, 3, ...]}
    """
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No ids provided")

    db.execute(
        update(Article)
        .where(Article.id.in_(ids))
        .values(synced=True)
    )
    db.commit()
    return {"acked": len(ids)}


@app.get("/api/articles/search")
def search_articles(
    source: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(_verify_token),
    db: Session = Depends(get_db),
):
    """Search/browse collected articles with filters."""
    query = db.query(Article)

    if source:
        query = query.filter(Article.source == source)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(Article.published_at >= since_dt)
        except ValueError:
            raise HTTPException(400, "Invalid 'since' datetime")
    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            query = query.filter(Article.published_at <= until_dt)
        except ValueError:
            raise HTTPException(400, "Invalid 'until' datetime")
    if q:
        query = query.filter(Article.title.ilike(f"%{q}%"))

    total = query.count()
    rows = (
        query
        .order_by(Article.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "count": len(rows),
        "articles": [r.to_dict() for r in rows],
    }


@app.get("/api/stats")
def get_stats(
    _: None = Depends(_verify_token),
    db: Session = Depends(get_db),
):
    """Per-source article counts and sync status."""
    rows = (
        db.query(
            Article.source,
            func.count(Article.id).label("total"),
            func.count(Article.id).filter(Article.synced == True).label("synced"),  # noqa: E712
            func.count(Article.id).filter(Article.synced == False).label("pending"),  # noqa: E712
            func.max(Article.collected_at).label("last_collected"),
        )
        .group_by(Article.source)
        .all()
    )
    return {
        "sources": [
            {
                "source": r.source,
                "total": r.total,
                "synced": r.synced,
                "pending": r.pending,
                "last_collected": r.last_collected.isoformat() if r.last_collected else None,
            }
            for r in rows
        ]
    }
