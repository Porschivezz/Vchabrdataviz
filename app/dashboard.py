"""Streamlit dashboard with public and admin views."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import func, select, text

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings  # noqa: E402
from src.core.database import get_session, init_db  # noqa: E402
from src.core.models import Article  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialise DB on first run
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_database():
    init_db()
    return True

_init_database()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Monitoring Dashboard", page_icon="📊", layout="wide")

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ---------------------------------------------------------------------------
# Sidebar: Navigation & Auth
# ---------------------------------------------------------------------------

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Public Dashboard", "Admin Panel"])

st.sidebar.markdown("---")
st.sidebar.subheader("Admin Login")

password_input = st.sidebar.text_input("Password", type="password", key="admin_pwd")
if st.sidebar.button("Login"):
    if password_input == settings.admin_password:
        st.session_state.is_admin = True
        st.sidebar.success("Logged in as admin")
    else:
        st.session_state.is_admin = False
        st.sidebar.error("Wrong password")

if st.session_state.is_admin and st.sidebar.button("Logout"):
    st.session_state.is_admin = False
    st.rerun()


# ===================================================================
# Helper functions
# ===================================================================

def _get_status_counts() -> dict[str, int]:
    session = get_session()
    try:
        rows = session.execute(
            select(Article.status, func.count(Article.id)).group_by(Article.status)
        ).all()
        return {status: cnt for status, cnt in rows}
    finally:
        session.close()


def _get_pending_token_stats() -> dict:
    session = get_session()
    try:
        row = session.execute(
            select(
                func.count(Article.id),
                func.coalesce(func.sum(Article.estimated_tokens), 0),
            ).where(Article.status == "PENDING")
        ).one()
        count, total_tokens = row
        return {"count": count, "total_tokens": total_tokens}
    finally:
        session.close()


def _get_analyzed_articles() -> list[Article]:
    session = get_session()
    try:
        return (
            session.execute(
                select(Article)
                .where(Article.status == "ANALYZED")
                .order_by(Article.published_at.desc().nullslast())
            )
            .scalars()
            .all()
        )
    finally:
        session.close()


def _semantic_search(query_embedding: list[float], top_k: int = 10) -> list[dict]:
    """Cosine similarity search against analyzed articles."""
    session = get_session()
    try:
        vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        results = session.execute(
            text(
                """
                SELECT id, title, source, summary, link, published_at,
                       entities,
                       1 - (embedding <=> :vec ::vector) AS similarity
                FROM articles
                WHERE status = 'ANALYZED' AND embedding IS NOT NULL
                ORDER BY embedding <=> :vec ::vector
                LIMIT :k
                """
            ),
            {"vec": vec_literal, "k": top_k},
        ).fetchall()
        return [
            {
                "title": r.title,
                "source": r.source,
                "summary": r.summary,
                "link": r.link,
                "published_at": r.published_at,
                "entities": r.entities,
                "similarity": round(float(r.similarity), 4),
            }
            for r in results
        ]
    except Exception as exc:
        logger.error("Semantic search failed: %s", exc)
        return []
    finally:
        session.close()


def _get_articles_per_day() -> pd.DataFrame:
    """Articles per day per source already in DB."""
    session = get_session()
    try:
        rows = session.execute(
            text(
                """
                SELECT source,
                       DATE(published_at) AS day,
                       COUNT(*) AS cnt
                FROM articles
                WHERE published_at IS NOT NULL
                GROUP BY source, DATE(published_at)
                ORDER BY day DESC
                """
            )
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["source", "day", "cnt"])
        return pd.DataFrame(rows, columns=["source", "day", "cnt"])
    finally:
        session.close()


def _get_articles_per_day_status() -> pd.DataFrame:
    """Articles per day per source per status."""
    session = get_session()
    try:
        rows = session.execute(
            text(
                """
                SELECT source,
                       DATE(published_at) AS day,
                       status,
                       COUNT(*) AS cnt
                FROM articles
                WHERE published_at IS NOT NULL
                GROUP BY source, DATE(published_at), status
                ORDER BY day DESC, source
                """
            )
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["source", "day", "status", "cnt"])
        return pd.DataFrame(rows, columns=["source", "day", "status", "cnt"])
    finally:
        session.close()


# ===================================================================
# PUBLIC DASHBOARD
# ===================================================================

if page == "Public Dashboard":
    st.title("Article Monitor — Public Dashboard")

    articles = _get_analyzed_articles()

    if not articles:
        st.info("No analyzed articles yet. Waiting for ingestion and analysis.")
    else:
        # --- Semantic search ---
        st.subheader("Semantic Search")
        query = st.text_input("Search analyzed articles", placeholder="Enter a topic...")

        if query:
            from src.nlp.openrouter import OpenRouterProvider
            provider = OpenRouterProvider()
            q_emb = provider.embed(query)
            results = _semantic_search(q_emb)

            if results:
                for r in results:
                    with st.expander(
                        f"[{r['source'].upper()}] {r['title']} (sim: {r['similarity']})"
                    ):
                        st.write(r["summary"])
                        if r["entities"]:
                            st.json(r["entities"])
                        st.markdown(f"[Read original]({r['link']})")
            else:
                st.warning("No matching articles found.")

        # --- Trends: top entities ---
        st.subheader("Trends — Top Extracted Entities")

        all_techs: list[str] = []
        all_orgs: list[str] = []
        all_signals: list[str] = []

        for a in articles:
            if a.entities and isinstance(a.entities, dict):
                all_techs.extend(a.entities.get("technologies", []))
                all_orgs.extend(a.entities.get("organizations", []))
                all_signals.extend(a.entities.get("weak_signals", []))

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Technologies**")
            if all_techs:
                tech_df = pd.Series(all_techs).value_counts().head(15)
                st.bar_chart(tech_df)
            else:
                st.caption("No data yet")

        with col2:
            st.markdown("**Organizations**")
            if all_orgs:
                org_df = pd.Series(all_orgs).value_counts().head(15)
                st.bar_chart(org_df)
            else:
                st.caption("No data yet")

        with col3:
            st.markdown("**Weak Signals**")
            if all_signals:
                sig_df = pd.Series(all_signals).value_counts().head(15)
                st.bar_chart(sig_df)
            else:
                st.caption("No data yet")

        # --- Article cards ---
        st.subheader("Analyzed Articles")

        rows = []
        for a in articles:
            rows.append({
                "Source": a.source,
                "Title": a.title,
                "Published": str(a.published_at or ""),
                "Summary": (a.summary or "")[:200],
                "Link": a.link,
            })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                column_config={"Link": st.column_config.LinkColumn("Link")},
                use_container_width=True,
                hide_index=True,
            )


# ===================================================================
# ADMIN PANEL
# ===================================================================

elif page == "Admin Panel":
    st.title("Admin Panel")

    if not st.session_state.is_admin:
        st.warning("Please log in via the sidebar to access the Admin Panel.")
        st.stop()

    # --- Status metrics ---
    st.subheader("Ingestion Stats")
    counts = _get_status_counts()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PENDING", counts.get("PENDING", 0))
    c2.metric("QUEUED", counts.get("QUEUED_FOR_ANALYSIS", 0))
    c3.metric("ANALYZED", counts.get("ANALYZED", 0))
    total_in_db = sum(counts.values())
    c4.metric("Total in DB", total_in_db)

    # --- Detailed per-day per-source breakdown ---
    st.subheader("Articles per Day (by Source)")

    day_df = _get_articles_per_day()
    if not day_df.empty:
        # Pivot table: rows=day, columns=source, values=count
        pivot = day_df.pivot_table(
            index="day", columns="source", values="cnt",
            fill_value=0, aggfunc="sum",
        )
        pivot = pivot.sort_index(ascending=False)
        pivot["TOTAL"] = pivot.sum(axis=1)

        # Show as a clear table
        st.dataframe(
            pivot.reset_index().rename(columns={"day": "Date"}),
            use_container_width=True,
            hide_index=True,
        )

        # Chart
        chart_pivot = day_df.pivot_table(
            index="day", columns="source", values="cnt",
            fill_value=0, aggfunc="sum",
        ).sort_index()
        st.bar_chart(chart_pivot)

        # Today / yesterday summary
        from datetime import date as dt_date
        today_d = dt_date.today()
        yesterday_d = today_d - timedelta(days=1)

        today_total = int(pivot.loc[today_d, "TOTAL"]) if today_d in pivot.index else 0
        yesterday_total = int(pivot.loc[yesterday_d, "TOTAL"]) if yesterday_d in pivot.index else 0

        summary_cols = st.columns(2)
        with summary_cols[0]:
            today_detail = ""
            if today_d in pivot.index:
                today_detail = " | ".join(
                    f"{src}: {int(pivot.loc[today_d, src])}"
                    for src in pivot.columns if src != "TOTAL" and int(pivot.loc[today_d, src]) > 0
                )
            st.metric(f"Today ({today_d}), partial", f"{today_total} articles", help=today_detail)
        with summary_cols[1]:
            yest_detail = ""
            if yesterday_d in pivot.index:
                yest_detail = " | ".join(
                    f"{src}: {int(pivot.loc[yesterday_d, src])}"
                    for src in pivot.columns if src != "TOTAL" and int(pivot.loc[yesterday_d, src]) > 0
                )
            st.metric(f"Yesterday ({yesterday_d}), full day", f"{yesterday_total} articles", help=yest_detail)
    else:
        st.info("No articles in database yet.")

    # --- DB coverage ---
    from src.services.ingestion_service import get_db_date_coverage
    coverage = get_db_date_coverage()
    if coverage["total"] > 0:
        cov1, cov2 = st.columns(2)
        cov1.metric("Earliest article", str(coverage["min_date"].date()) if coverage["min_date"] else "—")
        cov2.metric("Latest article", str(coverage["max_date"].date()) if coverage["max_date"] else "—")

    # --- Cost estimation ---
    st.subheader("Cost Estimation for Pending Articles")
    pending = _get_pending_token_stats()
    total_tokens = pending["total_tokens"]
    est_input_cost = (total_tokens / 1_000_000) * settings.llm_input_cost_per_1m
    est_output_cost = (total_tokens * 0.15 / 1_000_000) * settings.llm_output_cost_per_1m
    est_embed_cost = (total_tokens / 1_000_000) * settings.embedding_cost_per_1m
    total_est = est_input_cost + est_output_cost + est_embed_cost

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("Pending articles", pending["count"])
    cc2.metric("Total tokens (approx)", f"{total_tokens:,}")
    cc3.metric("Est. LLM cost", f"${est_input_cost + est_output_cost:.4f}")
    cc4.metric("Est. total cost", f"${total_est:.4f}")

    # --- Actions ---
    st.subheader("Actions")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Ingest Articles by Date Range**")

        preset = st.selectbox(
            "Quick period",
            [
                "Yesterday + today",
                "Last 3 days",
                "Last 7 days",
                "Last 30 days",
                "Custom range",
            ],
            key="ingest_preset",
        )

        today = date.today()

        if preset == "Custom range":
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                since_date = st.date_input("From", value=today - timedelta(days=1), key="since")
            with d_col2:
                until_date = st.date_input("To", value=today, key="until")
        else:
            days_map = {
                "Yesterday + today": 1,
                "Last 3 days": 3,
                "Last 7 days": 7,
                "Last 30 days": 30,
            }
            days = days_map[preset]
            since_date = today - timedelta(days=days)
            until_date = today

        st.caption(f"Period: **{since_date}** — **{until_date}** (UTC)")

        if st.button("Run Ingestion", type="primary"):
            since_dt = datetime.combine(since_date, datetime.min.time(), tzinfo=timezone.utc)
            until_dt = datetime.combine(until_date, datetime.max.time(), tzinfo=timezone.utc)

            with st.spinner(f"Scraping articles from {since_date} to {until_date}..."):
                from src.services.ingestion_service import ingest_all
                stats = ingest_all(since=since_dt, until=until_dt)

            st.success(
                f"Done! Found {stats['total_fetched']} articles in range. "
                f"New: {stats['new']} (auto-queued: {stats['queued']}), "
                f"Already in DB: {stats['skipped']}"
            )
            st.rerun()

    with col_b:
        st.markdown("**Analyze Articles**")
        analyze_scope = st.selectbox(
            "Scope",
            ["QUEUED_FOR_ANALYSIS only", "PENDING only", "Both"],
        )
        analyze_batch = st.number_input("Batch size", min_value=1, max_value=50, value=10)

        if st.button("Run Analysis", type="primary"):
            with st.spinner("Running LLM analysis..."):
                from src.nlp.openrouter import OpenRouterProvider
                from src.services.analysis_service import (
                    analyze_all_unprocessed,
                    analyze_pending,
                    analyze_queued,
                )

                provider = OpenRouterProvider()
                if analyze_scope == "QUEUED_FOR_ANALYSIS only":
                    n = analyze_queued(provider, batch_size=analyze_batch)
                elif analyze_scope == "PENDING only":
                    n = analyze_pending(provider, batch_size=analyze_batch)
                else:
                    n = analyze_all_unprocessed(provider, batch_size=analyze_batch)

            st.success(f"Analyzed {n} articles.")
            st.rerun()

    # --- Recent articles table ---
    st.subheader("Recent Articles (all statuses)")
    session = get_session()
    try:
        all_articles = (
            session.execute(
                select(Article).order_by(Article.published_at.desc().nullslast()).limit(100)
            )
            .scalars()
            .all()
        )
    finally:
        session.close()

    if all_articles:
        rows = []
        for a in all_articles:
            rows.append({
                "Source": a.source,
                "Status": a.status,
                "Title": a.title[:80],
                "Tokens": a.estimated_tokens,
                "Tags": ", ".join(a.native_tags or [])[:100],
                "Published": str(a.published_at or ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No articles in database yet.")
