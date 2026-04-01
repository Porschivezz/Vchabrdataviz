"""Пульс Рунета — Streamlit dashboard with public and admin views."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func, select, text, and_, or_

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings  # noqa: E402
from src.core.database import get_session, init_db  # noqa: E402
from src.core.models import Article, DailyDigest, IngestionRun  # noqa: E402

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

st.set_page_config(page_title="Пульс Рунета", page_icon="📡", layout="wide")

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ---------------------------------------------------------------------------
# Sidebar: Navigation & Auth
# ---------------------------------------------------------------------------

st.sidebar.title("📡 Пульс Рунета")
page = st.sidebar.radio(
    "Навигация",
    ["Главная", "Поиск", "Тренды", "Семантическая карта", "Дайджесты", "Админ-панель"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Вход для администратора")

password_input = st.sidebar.text_input("Пароль", type="password", key="admin_pwd")
if st.sidebar.button("Войти"):
    if password_input == settings.admin_password:
        st.session_state.is_admin = True
        st.sidebar.success("Вы вошли как администратор")
    else:
        st.session_state.is_admin = False
        st.sidebar.error("Неверный пароль")

if st.session_state.is_admin and st.sidebar.button("Выйти"):
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


def _get_analyzed_articles(limit: int = 200) -> list[Article]:
    session = get_session()
    try:
        return (
            session.execute(
                select(Article)
                .where(Article.status == "ANALYZED")
                .order_by(Article.published_at.desc().nullslast())
                .limit(limit)
            )
            .scalars()
            .all()
        )
    finally:
        session.close()


def _get_articles_per_day() -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT source, DATE(published_at) AS day, COUNT(*) AS cnt
                FROM articles
                WHERE published_at IS NOT NULL
                GROUP BY source, DATE(published_at)
                ORDER BY day DESC
            """)
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["source", "day", "cnt"])
        return pd.DataFrame(rows, columns=["source", "day", "cnt"])
    finally:
        session.close()


def _get_articles_per_day_status() -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT source, DATE(published_at) AS day, status, COUNT(*) AS cnt
                FROM articles
                WHERE published_at IS NOT NULL
                GROUP BY source, DATE(published_at), status
                ORDER BY day DESC, source
            """)
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["source", "day", "status", "cnt"])
        return pd.DataFrame(rows, columns=["source", "day", "status", "cnt"])
    finally:
        session.close()


def _get_ingestion_runs(limit: int = 20) -> list:
    session = get_session()
    try:
        return session.execute(
            select(IngestionRun)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        ).scalars().all()
    finally:
        session.close()


def _get_sentiment_stats(days: int = 7) -> pd.DataFrame:
    """Sentiment distribution per source per day."""
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = session.execute(
            text("""
                SELECT source,
                       DATE(published_at) AS day,
                       AVG(sentiment) AS avg_sentiment,
                       COUNT(*) AS cnt
                FROM articles
                WHERE status = 'ANALYZED'
                  AND sentiment IS NOT NULL
                  AND published_at >= :since
                GROUP BY source, DATE(published_at)
                ORDER BY day
            """),
            {"since": since},
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["source", "day", "avg_sentiment", "cnt"])
        return pd.DataFrame(rows, columns=["source", "day", "avg_sentiment", "cnt"])
    finally:
        session.close()


# ===================================================================
# PAGE: ГЛАВНАЯ (Home / Overview)
# ===================================================================

if page == "Главная":
    st.title("📡 Пульс Рунета")
    st.caption("Мониторинг технологических публикаций Хабра и VC.ru")

    articles = _get_analyzed_articles(limit=100)

    if not articles:
        st.info("Пока нет проанализированных статей. Запустите сбор и анализ в админ-панели.")
    else:
        # --- Key metrics ---
        counts = _get_status_counts()
        total = sum(counts.values())

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Всего статей", total)
        m2.metric("Проанализировано", counts.get("ANALYZED", 0))

        sentiments = [a.sentiment for a in articles if a.sentiment is not None]
        avg_s = sum(sentiments) / len(sentiments) if sentiments else None
        if avg_s is not None:
            emoji = "😊" if avg_s > 0.1 else "😐" if avg_s > -0.1 else "😟"
            m3.metric("Ср. настроение", f"{emoji} {avg_s:+.2f}")
        else:
            m3.metric("Ср. настроение", "—")

        m4.metric("Источников", len(set(a.source for a in articles)))

        # --- Daily digest (latest) ---
        session = get_session()
        try:
            latest_digest = session.execute(
                select(DailyDigest)
                .where(DailyDigest.source == "all")
                .order_by(DailyDigest.digest_date.desc())
                .limit(1)
            ).scalars().first()
        finally:
            session.close()

        if latest_digest:
            st.subheader(f"Дайджест за {latest_digest.digest_date.strftime('%d.%m.%Y') if latest_digest.digest_date else '?'}")
            st.markdown(latest_digest.narrative)
            st.markdown("---")

        # --- Sentiment radar ---
        sent_df = _get_sentiment_stats(days=14)
        if not sent_df.empty:
            st.subheader("Динамика настроений")
            fig = px.line(
                sent_df, x="day", y="avg_sentiment", color="source",
                title="Средний сентимент по дням",
                labels={"avg_sentiment": "Сентимент", "day": "Дата", "source": "Источник"},
            )
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)

        # --- Top entities ---
        st.subheader("Горячие сущности")

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
            st.markdown("**Технологии**")
            if all_techs:
                tech_counts = pd.Series(all_techs).value_counts().head(15)
                fig = px.bar(x=tech_counts.values, y=tech_counts.index, orientation="h",
                             labels={"x": "Упоминания", "y": ""})
                fig.update_layout(height=400, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Нет данных")

        with col2:
            st.markdown("**Организации**")
            if all_orgs:
                org_counts = pd.Series(all_orgs).value_counts().head(15)
                fig = px.bar(x=org_counts.values, y=org_counts.index, orientation="h",
                             labels={"x": "Упоминания", "y": ""})
                fig.update_layout(height=400, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Нет данных")

        with col3:
            st.markdown("**Слабые сигналы**")
            if all_signals:
                sig_counts = pd.Series(all_signals).value_counts().head(15)
                fig = px.bar(x=sig_counts.values, y=sig_counts.index, orientation="h",
                             labels={"x": "Упоминания", "y": ""})
                fig.update_layout(height=400, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Нет данных")

        # --- Recent articles ---
        st.subheader("Последние проанализированные статьи")
        rows = []
        for a in articles[:50]:
            sent_str = f"{a.sentiment:+.2f}" if a.sentiment is not None else ""
            rows.append({
                "Источник": a.source.upper(),
                "Заголовок": a.title[:80],
                "Опубликовано": str(a.published_at.strftime("%d.%m %H:%M") if a.published_at else ""),
                "Сентимент": sent_str,
                "Резюме": (a.summary or "")[:150],
                "Ссылка": a.link,
            })
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                column_config={"Ссылка": st.column_config.LinkColumn("Ссылка")},
                use_container_width=True,
                hide_index=True,
            )


# ===================================================================
# PAGE: ПОИСК (Hybrid Search)
# ===================================================================

elif page == "Поиск":
    st.title("🔍 Гибридный поиск")
    st.caption("Семантический + полнотекстовый поиск по проанализированным статьям")

    query = st.text_input("Поисковый запрос", placeholder="Введите тему для поиска...")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        top_k = st.slider("Количество результатов", 5, 50, 20)
    with col_s2:
        vec_weight = st.slider("Вес семантики", 0.0, 1.0, 0.6, 0.1)

    if query:
        from src.nlp.openrouter import OpenRouterProvider
        from src.services.search_service import hybrid_search

        with st.spinner("Ищем..."):
            provider = OpenRouterProvider()
            q_emb = provider.embed(query)
            results = hybrid_search(
                query, q_emb,
                top_k=top_k,
                vector_weight=vec_weight,
                fts_weight=1.0 - vec_weight,
            )

        if results:
            st.success(f"Найдено {len(results)} результатов")
            for r in results:
                with st.expander(
                    f"[{r['source'].upper()}] {r['title']} "
                    f"(релевантность: {r['combined_score']:.3f})"
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Семантика", f"{r['vec_score']:.3f}")
                    c2.metric("Текстовый", f"{r['fts_score']:.3f}")
                    if r.get("sentiment") is not None:
                        c3.metric("Сентимент", f"{r['sentiment']:+.2f}")
                    st.write(r["summary"])
                    if r["entities"]:
                        st.json(r["entities"])
                    st.markdown(f"[Читать оригинал]({r['link']})")
        else:
            st.warning("Ничего не найдено.")


# ===================================================================
# PAGE: ТРЕНДЫ (Trends)
# ===================================================================

elif page == "Тренды":
    st.title("📈 Тренды и скорость упоминаний")

    from src.services.trend_service import compute_trend_velocity, get_entity_timeline

    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        window = st.selectbox("Окно (дни)", [3, 7, 14], index=1)
    with col_t2:
        compare = st.selectbox("Сравнение (дни)", [7, 14, 30], index=0)
    with col_t3:
        min_ment = st.number_input("Мин. упоминаний", 1, 20, 3)

    trends = compute_trend_velocity(
        window_days=window, compare_days=compare, min_mentions=min_ment
    )

    if trends:
        # Top accelerating
        st.subheader("Растущие тренды")
        rising = [t for t in trends if t["velocity"] > 0][:20]
        if rising:
            df_r = pd.DataFrame(rising)
            fig = px.bar(
                df_r, x="velocity", y="entity", color="category",
                orientation="h",
                title=f"Ускорение упоминаний ({window}д vs предыдущие {compare}д)",
                labels={"velocity": "Скорость", "entity": "", "category": "Категория"},
            )
            fig.update_layout(height=max(300, len(rising) * 30), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

        # Entity timeline
        st.subheader("Таймлайн сущности")
        entity_name = st.text_input("Имя сущности", placeholder="Например: GPT-4, Yandex...")
        if entity_name:
            timeline = get_entity_timeline(entity_name, days=30)
            if timeline:
                tl_df = pd.DataFrame(timeline)
                fig = px.bar(tl_df, x="date", y="count",
                             title=f"Упоминания «{entity_name}» за 30 дней",
                             labels={"count": "Упоминания", "date": "Дата"})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(f"«{entity_name}» не найден в данных.")

        # Full table
        st.subheader("Все тренды")
        st.dataframe(
            pd.DataFrame(trends[:50]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Недостаточно данных для анализа трендов. Нужен хотя бы 1 день проанализированных статей.")


# ===================================================================
# PAGE: СЕМАНТИЧЕСКАЯ КАРТА
# ===================================================================

elif page == "Семантическая карта":
    st.title("🗺️ Семантическая карта статей")
    st.caption("2D-проекция эмбеддингов (UMAP/PCA) с кластеризацией")

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        map_days = st.selectbox("Период (дни)", [3, 7, 14, 30], index=1)
    with col_m2:
        n_neighbors = st.slider("UMAP n_neighbors", 5, 50, 15)

    if st.button("Построить карту", type="primary"):
        from src.services.semantic_map_service import compute_semantic_map

        with st.spinner("Вычисляем проекцию..."):
            result = compute_semantic_map(days=map_days, n_neighbors=n_neighbors)

        if result["points"]:
            df = pd.DataFrame(result["points"])
            fig = px.scatter(
                df, x="x", y="y",
                color="cluster",
                symbol="source",
                hover_data=["title", "source", "sentiment"],
                title=f"Семантическая карта ({len(df)} статей, {result['n_clusters']} кластеров)",
                labels={"x": "UMAP-1", "y": "UMAP-2", "cluster": "Кластер"},
                color_continuous_scale="Viridis",
            )
            fig.update_layout(height=700)
            fig.update_traces(marker=dict(size=6, opacity=0.7))
            st.plotly_chart(fig, use_container_width=True)

            # Cluster summary
            st.subheader("Статьи по кластерам")
            for cluster_id in sorted(df["cluster"].unique()):
                cluster_df = df[df["cluster"] == cluster_id]
                with st.expander(f"Кластер {cluster_id} ({len(cluster_df)} статей)"):
                    for _, row in cluster_df.head(10).iterrows():
                        st.write(f"- [{row['source'].upper()}] {row['title']}")
        else:
            st.warning("Недостаточно статей с эмбеддингами для построения карты (нужно >= 5).")


# ===================================================================
# PAGE: ДАЙДЖЕСТЫ
# ===================================================================

elif page == "Дайджесты":
    st.title("📰 Ежедневные дайджесты")

    session = get_session()
    try:
        digests = session.execute(
            select(DailyDigest)
            .where(DailyDigest.source == "all")
            .order_by(DailyDigest.digest_date.desc())
            .limit(30)
        ).scalars().all()
    finally:
        session.close()

    if not digests:
        st.info("Дайджестов пока нет. Они генерируются автоматически через Celery или вручную в админ-панели.")
    else:
        for d in digests:
            date_str = d.digest_date.strftime("%d.%m.%Y") if d.digest_date else "?"
            sent_str = f" | Настроение: {d.avg_sentiment:+.2f}" if d.avg_sentiment is not None else ""
            with st.expander(f"📰 {date_str} — {d.article_count} статей{sent_str}"):
                st.markdown(d.narrative)
                if d.top_entities:
                    st.markdown("**Топ сущности:**")
                    st.json(d.top_entities)


# ===================================================================
# ADMIN PANEL
# ===================================================================

elif page == "Админ-панель":
    st.title("⚙️ Админ-панель")

    if not st.session_state.is_admin:
        st.warning("Пожалуйста, войдите через боковую панель для доступа к админ-панели.")
        st.stop()

    # --- Tabs ---
    tab_overview, tab_ingest, tab_analyze, tab_digest, tab_sources, tab_runs = st.tabs([
        "Обзор", "Сбор", "Анализ", "Дайджесты", "Источники", "История запусков"
    ])

    # --- TAB: Overview ---
    with tab_overview:
        st.subheader("Статистика")
        counts = _get_status_counts()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("PENDING", counts.get("PENDING", 0))
        c2.metric("QUEUED", counts.get("QUEUED_FOR_ANALYSIS", 0))
        c3.metric("ANALYZED", counts.get("ANALYZED", 0))
        c4.metric("Всего в БД", sum(counts.values()))

        # Per-day per-source
        st.subheader("Статьи по дням (по источникам)")
        day_df = _get_articles_per_day()
        if not day_df.empty:
            pivot = day_df.pivot_table(
                index="day", columns="source", values="cnt",
                fill_value=0, aggfunc="sum",
            )
            pivot = pivot.sort_index(ascending=False)
            pivot["TOTAL"] = pivot.sum(axis=1)

            st.dataframe(
                pivot.reset_index().rename(columns={"day": "Дата"}),
                use_container_width=True, hide_index=True,
            )

            # Chart
            chart_pivot = day_df.pivot_table(
                index="day", columns="source", values="cnt",
                fill_value=0, aggfunc="sum",
            ).sort_index()

            fig = px.bar(
                chart_pivot.reset_index().melt(id_vars="day", var_name="source", value_name="count"),
                x="day", y="count", color="source", barmode="group",
                title="Статьи по дням",
                labels={"count": "Количество", "day": "Дата", "source": "Источник"},
            )
            st.plotly_chart(fig, use_container_width=True)

            # Today / yesterday
            today_d = date.today()
            yesterday_d = today_d - timedelta(days=1)

            today_total = int(pivot.loc[today_d, "TOTAL"]) if today_d in pivot.index else 0
            yest_total = int(pivot.loc[yesterday_d, "TOTAL"]) if yesterday_d in pivot.index else 0

            sc1, sc2 = st.columns(2)
            with sc1:
                detail = ""
                if today_d in pivot.index:
                    detail = " | ".join(
                        f"{src}: {int(pivot.loc[today_d, src])}"
                        for src in pivot.columns if src != "TOTAL" and int(pivot.loc[today_d, src]) > 0
                    )
                st.metric(f"Сегодня ({today_d})", f"{today_total} статей", help=detail)
            with sc2:
                detail = ""
                if yesterday_d in pivot.index:
                    detail = " | ".join(
                        f"{src}: {int(pivot.loc[yesterday_d, src])}"
                        for src in pivot.columns if src != "TOTAL" and int(pivot.loc[yesterday_d, src]) > 0
                    )
                st.metric(f"Вчера ({yesterday_d})", f"{yest_total} статей", help=detail)
        else:
            st.info("В базе пока нет статей.")

        # Coverage
        from src.services.ingestion_service import get_db_date_coverage
        coverage = get_db_date_coverage()
        if coverage["total"] > 0:
            cov1, cov2 = st.columns(2)
            cov1.metric("Самая ранняя", str(coverage["min_date"].date()) if coverage["min_date"] else "—")
            cov2.metric("Самая поздняя", str(coverage["max_date"].date()) if coverage["max_date"] else "—")

        # Cost estimation
        st.subheader("Оценка стоимости анализа")
        pending = _get_pending_token_stats()
        total_tokens = pending["total_tokens"]
        est_input = (total_tokens / 1_000_000) * settings.llm_input_cost_per_1m
        est_output = (total_tokens * 0.15 / 1_000_000) * settings.llm_output_cost_per_1m
        est_embed = (total_tokens / 1_000_000) * settings.embedding_cost_per_1m
        total_est = est_input + est_output + est_embed

        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("Ожидающих статей", pending["count"])
        cc2.metric("Токенов (прибл.)", f"{total_tokens:,}")
        cc3.metric("Стоимость LLM", f"${est_input + est_output:.4f}")
        cc4.metric("Общая стоимость", f"${total_est:.4f}")

    # --- TAB: Ingestion ---
    with tab_ingest:
        st.subheader("Сбор статей по диапазону дат")

        preset = st.selectbox(
            "Быстрый выбор периода",
            ["Вчера + сегодня", "Последние 3 дня", "Последние 7 дней",
             "Последние 30 дней", "Произвольный диапазон"],
            key="ingest_preset",
        )

        today = date.today()

        if preset == "Произвольный диапазон":
            d1, d2 = st.columns(2)
            with d1:
                since_date = st.date_input("С", value=today - timedelta(days=1), key="since")
            with d2:
                until_date = st.date_input("По", value=today, key="until")
        else:
            days_map = {
                "Вчера + сегодня": 1,
                "Последние 3 дня": 3,
                "Последние 7 дней": 7,
                "Последние 30 дней": 30,
            }
            since_date = today - timedelta(days=days_map[preset])
            until_date = today

        # Source selection
        from src.scrapers.registry import get_all_sources
        all_sources = get_all_sources()
        selected_sources = st.multiselect(
            "Источники",
            options=list(all_sources.keys()),
            default=list(all_sources.keys()),
            format_func=lambda x: f"{all_sources[x].icon} {all_sources[x].description}",
        )

        st.caption(f"Период: **{since_date}** — **{until_date}** (UTC)")

        if st.button("Запустить сбор", type="primary", key="run_ingest"):
            since_dt = datetime.combine(since_date, datetime.min.time(), tzinfo=timezone.utc)
            until_dt = datetime.combine(until_date, datetime.max.time(), tzinfo=timezone.utc)

            with st.spinner(f"Собираем статьи с {since_date} по {until_date}..."):
                from src.services.ingestion_service import ingest_all
                stats = ingest_all(since=since_dt, until=until_dt, sources=selected_sources)

            st.success(
                f"Готово! Найдено {stats['total_fetched']} статей. "
                f"Новых: {stats['new']} (авто-очередь: {stats['queued']}), "
                f"Уже в БД: {stats['skipped']}"
            )
            st.rerun()

    # --- TAB: Analysis ---
    with tab_analyze:
        st.subheader("Анализ статей по диапазону дат")

        a_preset = st.selectbox(
            "Быстрый выбор периода",
            ["Вчера + сегодня", "Последние 3 дня", "Последние 7 дней",
             "Последние 30 дней", "Произвольный диапазон"],
            key="analyze_preset",
        )

        if a_preset == "Произвольный диапазон":
            ad1, ad2 = st.columns(2)
            with ad1:
                a_since = st.date_input("С", value=today - timedelta(days=1), key="a_since")
            with ad2:
                a_until = st.date_input("По", value=today, key="a_until")
        else:
            a_days = {"Вчера + сегодня": 1, "Последние 3 дня": 3, "Последние 7 дней": 7, "Последние 30 дней": 30}
            a_since = today - timedelta(days=a_days[a_preset])
            a_until = today

        analyze_scope = st.selectbox(
            "Область",
            ["QUEUED + PENDING", "Только QUEUED_FOR_ANALYSIS", "Только PENDING"],
        )

        scope_map = {
            "QUEUED + PENDING": ["QUEUED_FOR_ANALYSIS", "PENDING"],
            "Только QUEUED_FOR_ANALYSIS": ["QUEUED_FOR_ANALYSIS"],
            "Только PENDING": ["PENDING"],
        }

        a_since_dt = datetime.combine(a_since, datetime.min.time(), tzinfo=timezone.utc)
        a_until_dt = datetime.combine(a_until, datetime.max.time(), tzinfo=timezone.utc)

        a_session = get_session()
        try:
            a_status_conds = [Article.status == s for s in scope_map[analyze_scope]]
            pending_count = a_session.execute(
                select(func.count(Article.id)).where(
                    and_(
                        or_(*a_status_conds),
                        Article.published_at >= a_since_dt,
                        Article.published_at <= a_until_dt,
                    )
                )
            ).scalar()
        finally:
            a_session.close()

        st.info(f"Статей к анализу: **{pending_count}**")

        if st.button("Запустить анализ", type="primary", key="run_analyze"):
            with st.spinner(f"Анализируем {pending_count} статей с {a_since} по {a_until}..."):
                from src.nlp.openrouter import OpenRouterProvider
                from src.services.analysis_service import analyze_by_date_range

                provider = OpenRouterProvider()
                n = analyze_by_date_range(
                    provider,
                    since=a_since_dt,
                    until=a_until_dt,
                    statuses=scope_map[analyze_scope],
                )

            st.success(f"Проанализировано {n} / {pending_count} статей.")
            st.rerun()

    # --- TAB: Digest ---
    with tab_digest:
        st.subheader("Генерация дайджеста")

        digest_date = st.date_input("Дата для дайджеста", value=today - timedelta(days=1), key="digest_date")

        if st.button("Сгенерировать дайджест", type="primary", key="run_digest"):
            from src.services.digest_service import build_daily_digest

            with st.spinner(f"Генерируем дайджест за {digest_date}..."):
                result = build_daily_digest(digest_date)

            if result["narrative"]:
                st.success(f"Дайджест готов: {result['article_count']} статей")
                st.markdown(result["narrative"])
            else:
                st.warning("Нет проанализированных статей за эту дату.")

    # --- TAB: Sources ---
    with tab_sources:
        st.subheader("Зарегистрированные источники")

        from src.scrapers.registry import get_all_sources
        sources = get_all_sources()

        for name, config in sources.items():
            with st.expander(f"{config.icon} {name} — {'включен' if config.enabled else 'выключен'}"):
                st.write(f"**Описание:** {config.description}")
                st.write(f"**Интервал опроса:** {config.poll_interval_minutes} мин")
                st.write(f"**Класс:** `{config.scraper_class.__name__}`")

    # --- TAB: Ingestion Runs ---
    with tab_runs:
        st.subheader("История запусков сбора")

        runs = _get_ingestion_runs(limit=30)
        if runs:
            rows = []
            for r in runs:
                rows.append({
                    "Источник": r.source,
                    "Период": f"{r.since.strftime('%d.%m')} — {r.until.strftime('%d.%m')}",
                    "Статус": r.status,
                    "Найдено": r.total_fetched,
                    "Новых": r.new_articles,
                    "Пропущено": r.skipped,
                    "Начало": r.started_at.strftime("%d.%m %H:%M") if r.started_at else "",
                    "Конец": r.finished_at.strftime("%d.%m %H:%M") if r.finished_at else "—",
                    "Ошибка": (r.error_message or "")[:100],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Запусков пока не было.")

    # --- Recent articles table ---
    st.markdown("---")
    st.subheader("Последние статьи (все статусы)")
    session = get_session()
    try:
        all_articles = (
            session.execute(
                select(Article).order_by(Article.published_at.desc().nullslast()).limit(100)
            ).scalars().all()
        )
    finally:
        session.close()

    if all_articles:
        rows = []
        for a in all_articles:
            rows.append({
                "Источник": a.source,
                "Статус": a.status,
                "Заголовок": a.title[:80],
                "Токены": a.estimated_tokens,
                "Теги": ", ".join(a.native_tags or [])[:100],
                "Опубликовано": str(a.published_at or ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("В базе пока нет статей.")
