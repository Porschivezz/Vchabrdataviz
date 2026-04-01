"""Semantic map service — UMAP projection of article embeddings."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, and_

from src.core.config import settings
from src.core.database import get_session
from src.core.models import Article

logger = logging.getLogger(__name__)


def compute_semantic_map(
    *,
    days: int = 7,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
) -> dict:
    """Compute 2D UMAP projection of article embeddings.

    Returns {"points": [{"x", "y", "title", "source", "id", "cluster"}], "n_clusters": int}.
    """
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        articles = (
            session.execute(
                select(Article).where(
                    and_(
                        Article.status == "ANALYZED",
                        Article.embedding.isnot(None),
                        Article.published_at >= since,
                    )
                )
                .order_by(Article.published_at.desc())
                .limit(2000)
            ).scalars().all()
        )

        if len(articles) < 5:
            return {"points": [], "n_clusters": 0}

        # Build embedding matrix
        dim = settings.embedding_dimensions
        embeddings = []
        valid_articles = []

        for a in articles:
            if a.embedding and len(a.embedding) == dim:
                vec = list(a.embedding)
                if any(v != 0.0 for v in vec):
                    embeddings.append(vec)
                    valid_articles.append(a)

        if len(embeddings) < 5:
            return {"points": [], "n_clusters": 0}

        X = np.array(embeddings)

        # UMAP projection
        try:
            import umap
            reducer = umap.UMAP(
                n_components=2,
                n_neighbors=min(n_neighbors, len(X) - 1),
                min_dist=min_dist,
                random_state=42,
                metric="cosine",
            )
            coords = reducer.fit_transform(X)
        except ImportError:
            logger.warning("umap-learn not installed, falling back to PCA")
            from sklearn.decomposition import PCA
            pca = PCA(n_components=2, random_state=42)
            coords = pca.fit_transform(X)

        # Clustering with HDBSCAN or KMeans fallback
        try:
            from sklearn.cluster import HDBSCAN
            clusterer = HDBSCAN(min_cluster_size=max(3, len(X) // 20))
            labels = clusterer.fit_predict(coords)
        except (ImportError, Exception):
            from sklearn.cluster import KMeans
            n_clusters = min(max(3, len(X) // 15), 15)
            labels = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(coords)

        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

        points = []
        for i, a in enumerate(valid_articles):
            points.append({
                "x": float(coords[i, 0]),
                "y": float(coords[i, 1]),
                "title": a.title[:80],
                "source": a.source,
                "id": str(a.id),
                "cluster": int(labels[i]),
                "sentiment": a.sentiment,
            })

        return {"points": points, "n_clusters": n_clusters}

    finally:
        session.close()
