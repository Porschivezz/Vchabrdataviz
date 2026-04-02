"""Knowledge Graph service — build entity relationship graphs from extracted triples."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from src.core.database import get_session
from src.core.models import Article

logger = logging.getLogger(__name__)


def build_knowledge_graph(
    *,
    days: int = 7,
    min_edge_weight: int = 1,
    max_nodes: int = 80,
) -> dict:
    """Build a knowledge graph from extracted relationship triples + co-occurrences.

    Returns {
        "nodes": [{"id": str, "label": str, "category": str, "size": int, "sentiment": float}],
        "edges": [{"source": str, "target": str, "label": str, "weight": int, "color": str}],
    }
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

        # --- Collect nodes from entities ---
        node_counts: dict[str, int] = defaultdict(int)
        node_categories: dict[str, str] = {}
        node_sentiments: dict[str, list[float]] = defaultdict(list)

        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            for cat, items in a.entities.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    node_counts[item] += 1
                    node_categories[item] = cat
                    if a.sentiment is not None:
                        node_sentiments[item].append(a.sentiment)

        # --- Collect edges from explicit triples ---
        edge_data: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"labels": defaultdict(int), "total": 0, "sentiments": []}
        )

        for a in articles:
            if not a.relations or not isinstance(a.relations, list):
                continue
            for rel in a.relations:
                if not isinstance(rel, dict):
                    continue
                subj = rel.get("subject", "").strip()
                obj = rel.get("object", "").strip()
                pred = rel.get("predicate", "").strip()
                if not subj or not obj or not pred:
                    continue

                key = (subj, obj) if subj < obj else (obj, subj)
                edge_data[key]["labels"][pred] += 1
                edge_data[key]["total"] += 1
                if a.sentiment is not None:
                    edge_data[key]["sentiments"].append(a.sentiment)

                # Ensure both nodes exist
                if subj not in node_counts:
                    node_counts[subj] = 1
                    node_categories[subj] = "relation"
                if obj not in node_counts:
                    node_counts[obj] = 1
                    node_categories[obj] = "relation"

        # --- Also add co-occurrence edges ---
        for a in articles:
            if not a.entities or not isinstance(a.entities, dict):
                continue
            all_entities_in_article = []
            for cat, items in a.entities.items():
                if isinstance(items, list):
                    all_entities_in_article.extend(items)

            # Pairwise co-occurrence
            for i in range(len(all_entities_in_article)):
                for j in range(i + 1, len(all_entities_in_article)):
                    e1 = all_entities_in_article[i]
                    e2 = all_entities_in_article[j]
                    if e1 == e2:
                        continue
                    key = (e1, e2) if e1 < e2 else (e2, e1)
                    if key not in edge_data:
                        edge_data[key] = {"labels": defaultdict(int), "total": 0, "sentiments": []}
                    edge_data[key]["labels"]["упоминается вместе"] += 1
                    edge_data[key]["total"] += 1

        # --- Build output, limited to top nodes ---
        top_nodes = sorted(node_counts.items(), key=lambda x: -x[1])[:max_nodes]
        top_node_ids = {n[0] for n in top_nodes}

        # Category colors
        cat_colors = {
            "technologies": "#00d4ff",
            "organizations": "#ff6b6b",
            "persons": "#ffd93d",
            "weak_signals": "#6bcb77",
            "relation": "#c084fc",
        }

        nodes = []
        for name, count in top_nodes:
            cat = node_categories.get(name, "relation")
            sents = node_sentiments.get(name, [])
            avg_sent = sum(sents) / len(sents) if sents else 0.0
            nodes.append({
                "id": name,
                "label": name,
                "category": cat,
                "size": min(count * 3 + 10, 60),
                "color": cat_colors.get(cat, "#888888"),
                "mentions": count,
                "sentiment": round(avg_sent, 2),
            })

        edges = []
        # Predicate sentiment colors
        positive_predicates = {"партнёрство с", "инвестирует в", "запускает", "использует", "сотрудничает"}
        negative_predicates = {"судится с", "конкурирует с", "блокирует", "критикует"}

        for (src, tgt), data in edge_data.items():
            if src not in top_node_ids or tgt not in top_node_ids:
                continue
            if data["total"] < min_edge_weight:
                continue

            # Pick the most common predicate
            top_label = max(data["labels"], key=data["labels"].get)

            # Color by predicate sentiment
            if top_label in positive_predicates:
                color = "#4ade80"  # green
            elif top_label in negative_predicates:
                color = "#f87171"  # red
            else:
                color = "#94a3b8"  # neutral gray

            edges.append({
                "source": src,
                "target": tgt,
                "label": top_label,
                "weight": data["total"],
                "color": color,
            })

        return {"nodes": nodes, "edges": edges}

    finally:
        session.close()


def get_entity_context(entity_name: str, *, days: int = 7, limit: int = 10) -> list[dict]:
    """Get articles that mention a specific entity, with their relations."""
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
                .order_by(Article.published_at.desc())
            ).scalars().all()
        )

        results = []
        name_lower = entity_name.lower()

        for a in articles:
            mentioned = False
            if a.entities and isinstance(a.entities, dict):
                for cat, items in a.entities.items():
                    if isinstance(items, list):
                        for item in items:
                            if item.lower() == name_lower:
                                mentioned = True
                                break

            if mentioned:
                article_relations = []
                if a.relations and isinstance(a.relations, list):
                    for rel in a.relations:
                        if isinstance(rel, dict):
                            if (rel.get("subject", "").lower() == name_lower or
                                    rel.get("object", "").lower() == name_lower):
                                article_relations.append(rel)

                results.append({
                    "title": a.title,
                    "source": a.source,
                    "link": a.link,
                    "summary": a.summary,
                    "sentiment": a.sentiment,
                    "hype_score": a.hype_score,
                    "relations": article_relations,
                    "published_at": a.published_at,
                })

                if len(results) >= limit:
                    break

        return results

    finally:
        session.close()
