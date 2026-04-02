"""Пульс Рунета — Streamlit dashboard with glassmorphism UI."""

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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings
from src.core.database import get_session, init_db
from src.core.models import Article, DailyDigest, IngestionRun, TelegramChannel
from app.styles import inject_glassmorphism, glass_card, neon_header

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif"),
    margin=dict(l=40, r=40, t=50, b=40),
)


@st.cache_resource
def _init_database():
    init_db()
    return True

_init_database()

st.set_page_config(page_title="Пульс Рунета", page_icon="📡", layout="wide")
inject_glassmorphism()

# Auto-refresh every 5 minutes so dashboard stays live
st.markdown(
    '<meta http-equiv="refresh" content="300">',
    unsafe_allow_html=True,
)

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# ── Sidebar ──
st.sidebar.markdown("## 📡 Пульс Рунета")
page = st.sidebar.radio(
    "Навигация",
    [
        "Главная",
        "Граф Знаний",
        "Детектор Драмы",
        "Радар Будущего",
        "Поиск",
        "Тренды",
        "Семантическая карта",
        "Дайджесты",
        "Админ-панель",
    ],
)

st.sidebar.markdown("---")
pwd = st.sidebar.text_input("Пароль администратора", type="password", key="admin_pwd")
if st.sidebar.button("Войти"):
    if pwd == settings.admin_password:
        st.session_state.is_admin = True
        st.sidebar.success("Вы вошли как администратор")
    else:
        st.session_state.is_admin = False
        st.sidebar.error("Неверный пароль")

if st.session_state.is_admin and st.sidebar.button("Выйти"):
    st.session_state.is_admin = False
    st.rerun()


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _status_counts() -> dict[str, int]:
    s = get_session()
    try:
        rows = s.execute(select(Article.status, func.count(Article.id)).group_by(Article.status)).all()
        return {st: c for st, c in rows}
    finally:
        s.close()


def _analyzed(limit=200):
    s = get_session()
    try:
        return s.execute(
            select(Article).where(Article.status == "ANALYZED")
            .order_by(Article.published_at.desc().nullslast()).limit(limit)
        ).scalars().all()
    finally:
        s.close()


def _articles_per_day():
    s = get_session()
    try:
        rows = s.execute(text(
            "SELECT source, DATE(published_at) AS day, COUNT(*) AS cnt "
            "FROM articles WHERE published_at IS NOT NULL "
            "GROUP BY source, DATE(published_at) ORDER BY day DESC"
        )).fetchall()
        return pd.DataFrame(rows, columns=["source", "day", "cnt"]) if rows else pd.DataFrame(columns=["source", "day", "cnt"])
    finally:
        s.close()


def _sentiment_by_day(days=14):
    s = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = s.execute(text(
            "SELECT source, DATE(published_at) AS day, AVG(sentiment) AS avg_s, COUNT(*) AS cnt "
            "FROM articles WHERE status='ANALYZED' AND sentiment IS NOT NULL AND published_at >= :since "
            "GROUP BY source, DATE(published_at) ORDER BY day"
        ), {"since": since}).fetchall()
        return pd.DataFrame(rows, columns=["source", "day", "avg_sentiment", "cnt"]) if rows else pd.DataFrame()
    finally:
        s.close()


def _pending_tokens():
    s = get_session()
    try:
        r = s.execute(select(func.count(Article.id), func.coalesce(func.sum(Article.estimated_tokens), 0)).where(Article.status == "PENDING")).one()
        return {"count": r[0], "total_tokens": r[1]}
    finally:
        s.close()


# ═══════════════════════════════════════════════════════════════
# PAGE: ГЛАВНАЯ
# ═══════════════════════════════════════════════════════════════
if page == "Главная":
    neon_header("📡 Пульс Рунета", 1)
    st.caption("Мониторинг технологических публикаций Хабра и VC.ru")

    articles = _analyzed(100)
    if not articles:
        st.info("Пока нет проанализированных статей. Запустите сбор и анализ в админ-панели.")
    else:
        counts = _status_counts()
        total = sum(counts.values())
        sentiments = [a.sentiment for a in articles if a.sentiment is not None]
        avg_s = sum(sentiments) / len(sentiments) if sentiments else None

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Всего статей", total)
        m2.metric("Проанализировано", counts.get("ANALYZED", 0))
        if avg_s is not None:
            emoji = "😊" if avg_s > 0.1 else "😐" if avg_s > -0.1 else "😟"
            m3.metric("Ср. настроение", f"{emoji} {avg_s:+.2f}")
        else:
            m3.metric("Ср. настроение", "—")
        m4.metric("Источников", len(set(a.source for a in articles)))

        # Latest digest
        ses = get_session()
        try:
            latest_dig = ses.execute(
                select(DailyDigest).where(DailyDigest.source == "all")
                .order_by(DailyDigest.digest_date.desc()).limit(1)
            ).scalars().first()
        finally:
            ses.close()

        if latest_dig:
            neon_header(f"📰 Дайджест за {latest_dig.digest_date.strftime('%d.%m.%Y') if latest_dig.digest_date else '?'}", 3)
            glass_card(latest_dig.narrative.replace("\n", "<br>"), accent=True)

        # Sentiment chart
        sent_df = _sentiment_by_day(14)
        if not sent_df.empty:
            neon_header("💬 Динамика настроений", 3)
            fig = px.line(sent_df, x="day", y="avg_sentiment", color="source",
                          labels={"avg_sentiment": "Сентимент", "day": "Дата", "source": "Источник"})
            fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.2)")
            fig.update_layout(**PLOTLY_LAYOUT, height=350)
            st.plotly_chart(fig, use_container_width=True)

        # Top entities
        neon_header("🔥 Горячие сущности", 3)
        t_tech, t_org, t_sig = [], [], []
        for a in articles:
            if a.entities and isinstance(a.entities, dict):
                t_tech.extend(a.entities.get("technologies", []))
                t_org.extend(a.entities.get("organizations", []))
                t_sig.extend(a.entities.get("weak_signals", []))

        c1, c2, c3 = st.columns(3)
        for col, label, data in [(c1, "Технологии", t_tech), (c2, "Организации", t_org), (c3, "Слабые сигналы", t_sig)]:
            with col:
                st.markdown(f"**{label}**")
                if data:
                    vc = pd.Series(data).value_counts().head(12)
                    fig = px.bar(x=vc.values, y=vc.index, orientation="h", labels={"x": "", "y": ""})
                    fig.update_layout(**PLOTLY_LAYOUT, height=350, showlegend=False, yaxis=dict(autorange="reversed"))
                    fig.update_traces(marker_color="#a78bfa")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.caption("Нет данных")

        # Recent articles
        neon_header("📋 Последние статьи", 3)
        rows = [{
            "Источник": a.source.upper(), "Заголовок": a.title[:80],
            "Опубликовано": a.published_at.strftime("%d.%m %H:%M") if a.published_at else "",
            "Сент.": f"{a.sentiment:+.2f}" if a.sentiment is not None else "",
            "Ссылка": a.link,
        } for a in articles[:40]]
        if rows:
            st.dataframe(pd.DataFrame(rows), column_config={"Ссылка": st.column_config.LinkColumn()},
                         use_container_width=True, hide_index=True)



# ═══════════════════════════════════════════════════════════════
# PAGE: ГРАФ ЗНАНИЙ
# ═══════════════════════════════════════════════════════════════
elif page == "Граф Знаний":
    neon_header("🌐 Вселенная Знаний", 1)
    st.caption("Интерактивный граф связей между сущностями — кто с кем и как")

    gc1, gc2, gc3 = st.columns(3)
    with gc1:
        g_days = st.selectbox("Период (дни)", [3, 7, 14, 30], index=1, key="g_days")
    with gc2:
        g_min_edge = st.slider("Мин. вес связи", 1, 10, 1, key="g_min_edge")
    with gc3:
        g_max_nodes = st.slider("Макс. узлов", 20, 150, 60, key="g_max_nodes")

    if st.button("Построить граф", type="primary", key="build_graph"):
        from src.services.knowledge_graph_service import build_knowledge_graph
        with st.spinner("Строим граф знаний..."):
            graph_data = build_knowledge_graph(days=g_days, min_edge_weight=g_min_edge, max_nodes=g_max_nodes)

        if graph_data["nodes"]:
            try:
                from streamlit_agraph import agraph, Node, Edge, Config

                nodes = [
                    Node(
                        id=n["id"], label=n["label"], size=n["size"],
                        color=n["color"],
                        font={"color": "#e2e8f0", "size": 12},
                        title=f"{n['label']}\nУпоминаний: {n['mentions']}\nСентимент: {n['sentiment']:+.2f}",
                    )
                    for n in graph_data["nodes"]
                ]

                edges = [
                    Edge(
                        source=e["source"], target=e["target"],
                        label=e["label"] if e["weight"] > 1 else "",
                        color=e["color"],
                        width=min(e["weight"] * 1.5, 8),
                        title=f"{e['source']} → {e['label']} → {e['target']} (×{e['weight']})",
                    )
                    for e in graph_data["edges"]
                ]

                config = Config(
                    width=1200, height=700,
                    directed=True,
                    physics=True,
                    hierarchical=False,
                    nodeHighlightBehavior=True,
                    highlightColor="#a78bfa",
                    collapsible=True,
                    node={"labelProperty": "label"},
                    link={"labelProperty": "label", "renderLabel": True},
                )

                agraph(nodes=nodes, edges=edges, config=config)

            except ImportError:
                st.warning("streamlit-agraph не установлен. Показываю таблицу связей.")
                st.dataframe(pd.DataFrame(graph_data["edges"]), use_container_width=True, hide_index=True)

            # Stats
            st.markdown("---")
            gs1, gs2, gs3 = st.columns(3)
            gs1.metric("Узлов", len(graph_data["nodes"]))
            gs2.metric("Связей", len(graph_data["edges"]))
            cats = {}
            for n in graph_data["nodes"]:
                cats[n["category"]] = cats.get(n["category"], 0) + 1
            gs3.metric("Категорий", len(cats))

            # Legend
            neon_header("📊 Узлы по категориям", 3)
            for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
                color_map = {"technologies": "🔵", "organizations": "🔴", "persons": "🟡", "weak_signals": "🟢", "relation": "🟣"}
                st.write(f"{color_map.get(cat, '⚪')} {cat}: {count}")

            # Entity deep dive
            neon_header("🔎 Досье на сущность", 3)
            entity_pick = st.text_input("Введите имя сущности", key="entity_dive")
            if entity_pick:
                from src.services.knowledge_graph_service import get_entity_context
                ctx = get_entity_context(entity_pick, days=g_days, limit=8)
                if ctx:
                    for c in ctx:
                        with st.expander(f"[{c['source'].upper()}] {c['title'][:70]}"):
                            if c.get("sentiment") is not None:
                                st.caption(f"Сентимент: {c['sentiment']:+.2f} | Хайп: {c.get('hype_score', 0):.1f}")
                            st.write(c.get("summary", ""))
                            if c.get("relations"):
                                st.markdown("**Связи:**")
                                for r in c["relations"]:
                                    st.write(f"  {r['subject']} → {r['predicate']} → {r['object']}")
                            st.markdown(f"[Читать]({c['link']})")
                else:
                    st.info(f"«{entity_pick}» не найден.")
        else:
            st.warning("Недостаточно данных для построения графа.")



# ═══════════════════════════════════════════════════════════════
# PAGE: ДЕТЕКТОР ДРАМЫ
# ═══════════════════════════════════════════════════════════════
elif page == "Детектор Драмы":
    neon_header("⚡ Детектор Драмы", 1)
    st.caption("Поляризация мнений, цепные реакции хайпа и разломы между источниками")

    tab_polar, tab_chain, tab_drama = st.tabs(["🎭 Поляризация", "🔗 Цепные реакции", "🔥 Топ драмы"])

    with tab_polar:
        from src.services.polarization_service import detect_polarized_topics

        pc1, pc2 = st.columns(2)
        with pc1:
            p_days = st.selectbox("Период", [1, 3, 7, 14], index=1, key="p_days")
        with pc2:
            p_min = st.number_input("Мин. статей", 2, 20, 3, key="p_min")

        topics = detect_polarized_topics(days=p_days, min_articles=p_min, top_n=15)
        if topics:
            # Divergence chart
            df_p = pd.DataFrame([{"entity": t["entity"], "divergence": t["divergence"],
                                  "hype": t["overall_hype"], "articles": t["article_count"]} for t in topics])
            fig = px.bar(df_p, x="divergence", y="entity", orientation="h",
                         color="hype", color_continuous_scale="YlOrRd",
                         labels={"divergence": "Разлом", "entity": "", "hype": "Хайп"},
                         title="Темы с максимальным расхождением настроений")
            fig.update_layout(**PLOTLY_LAYOUT, height=max(300, len(df_p) * 35), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

            # Detailed cards
            for t in topics[:8]:
                with st.expander(f"🎭 {t['entity']} — разлом {t['divergence']:.2f} ({t['article_count']} статей)"):
                    cols = st.columns(len(t["sources"]))
                    for i, (src, data) in enumerate(t["sources"].items()):
                        with cols[i % len(cols)]:
                            color = "🟢" if data["avg_sentiment"] > 0.1 else "🟡" if data["avg_sentiment"] > -0.1 else "🔴"
                            st.metric(f"{src.upper()} {color}", f"{data['avg_sentiment']:+.2f}", f"{data['count']} статей")
                            for title in data["titles"][:2]:
                                st.caption(f"• {title[:60]}")
        else:
            st.info("Недостаточно данных для анализа поляризации.")

    with tab_chain:
        from src.services.polarization_service import detect_chain_reactions

        ch_days = st.selectbox("Период", [1, 3, 7], index=1, key="ch_days")
        chains = detect_chain_reactions(days=ch_days, min_articles=4, top_n=10)

        if chains:
            for ch in chains[:6]:
                with st.expander(f"🔗 {ch['entity']} — {ch['total_articles']} статей, {ch['sources_reached']} источников, пик хайпа {ch['peak_hype']}"):
                    tl_data = ch["timeline"]
                    if tl_data:
                        tl_df = pd.DataFrame(tl_data)
                        if "hour" in tl_df.columns and "source" in tl_df.columns:
                            fig = px.scatter(tl_df, x="hour", y="source", size=[8]*len(tl_df),
                                             color="sentiment", color_continuous_scale="RdYlGn",
                                             hover_data=["title"],
                                             title=f"Распространение «{ch['entity']}» по времени")
                            fig.update_layout(**PLOTLY_LAYOUT, height=250)
                            st.plotly_chart(fig, use_container_width=True)

                        for entry in tl_data[:5]:
                            st.caption(f"  {entry['hour']} [{entry['source']}] {entry['title'][:60]}")
        else:
            st.info("Цепных реакций пока не обнаружено.")

    with tab_drama:
        from src.services.polarization_service import get_drama_topics

        dr_days = st.selectbox("Период", [1, 3, 7], index=1, key="dr_days")
        dramas = get_drama_topics(days=dr_days, top_n=10)

        if dramas:
            df_dr = pd.DataFrame([{"entity": d["entity"], "avg_hype": d["avg_hype"],
                                   "articles": d["article_count"]} for d in dramas])
            fig = px.bar(df_dr, x="avg_hype", y="entity", orientation="h",
                         color="avg_hype", color_continuous_scale="Hot",
                         labels={"avg_hype": "Ср. хайп", "entity": ""},
                         title="🔥 Генераторы драмы")
            fig.update_layout(**PLOTLY_LAYOUT, height=max(250, len(df_dr) * 35), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

            for d in dramas[:5]:
                with st.expander(f"🔥 {d['entity']} — хайп {d['avg_hype']:.2f}"):
                    for art in d["top_articles"][:3]:
                        st.write(f"[{art['source'].upper()}] {art['title']}")
                        st.caption(f"  Хайп: {art['hype_score']:.2f} | Сент: {art.get('sentiment', 0):+.2f}")
        else:
            st.info("Данных о хайпе пока нет.")



# ═══════════════════════════════════════════════════════════════
# PAGE: РАДАР БУДУЩЕГО
# ═══════════════════════════════════════════════════════════════
elif page == "Радар Будущего":
    neon_header("🔮 Радар Будущего", 1)
    st.caption("Слабые сигналы — зарождающиеся тренды, которые могут изменить всё")

    from src.services.weak_signal_service import detect_weak_signals, generate_signal_forecast

    ws1, ws2 = st.columns(2)
    with ws1:
        ws_days = st.selectbox("Горизонт сканирования", [7, 14, 30], index=1, key="ws_days")
    with ws2:
        ws_max = st.slider("Макс. упоминаний (фильтр)", 3, 20, 8, key="ws_max")

    signals = detect_weak_signals(days=ws_days, max_mentions=ws_max, min_mentions=2)

    if signals:
        # Sonar visualization using polar scatter
        fig = go.Figure()
        for s in signals:
            r = 1.0 - s["recency_score"]  # more recent = closer to center
            theta = hash(s["signal"]) % 360  # deterministic angle
            size = s["mentions"] * 6 + 10
            color = f"rgba({int(255 * s['avg_hype'])}, {int(100 + 155 * (1 - s['avg_hype']))}, 100, 0.8)"

            fig.add_trace(go.Scatterpolar(
                r=[r],
                theta=[theta],
                mode="markers+text",
                marker=dict(size=size, color=color, line=dict(color="rgba(167,139,250,0.5)", width=1)),
                text=[s["signal"][:20]],
                textposition="top center",
                textfont=dict(color="#e2e8f0", size=10),
                hovertext=f"{s['signal']}<br>Упоминаний: {s['mentions']}<br>Хайп: {s['avg_hype']}<br>С: {s['first_seen']}",
                showlegend=False,
            ))

        # Sonar rings
        fig.update_layout(
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(visible=True, range=[0, 1.1], showticklabels=False,
                                gridcolor="rgba(99,102,241,0.15)"),
                angularaxis=dict(visible=False),
            ),
            **PLOTLY_LAYOUT,
            height=600,
            title="Сонар: центр = недавние, периферия = давние | размер = частота | цвет = хайп",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        neon_header("📋 Все сигналы", 3)

        for s in signals:
            hype_bar = "█" * int(s["avg_hype"] * 10) + "░" * (10 - int(s["avg_hype"] * 10))
            dist = "🔴" if s["recency_score"] > 0.7 else "🟡" if s["recency_score"] > 0.3 else "⚪"

            with st.expander(f"{dist} {s['signal']} — {s['mentions']}x упоминаний | хайп [{hype_bar}]"):
                sc1, sc2, sc3 = st.columns(3)
                sc1.metric("Упоминаний", s["mentions"])
                sc2.metric("Ср. хайп", f"{s['avg_hype']:.2f}")
                sc3.metric("Ср. сентимент", f"{s['avg_sentiment']:+.2f}")

                st.caption(f"Первое: {s['first_seen']} | Последнее: {s['last_seen']} | Источники: {', '.join(s['sources'])}")

                # Context articles
                for art in s["context_articles"][:3]:
                    st.write(f"• [{art['source'].upper()}] {art['title']}")

                # LLM Forecast
                if st.button(f"🔮 Сгенерировать прогноз", key=f"forecast_{s['signal'][:20]}"):
                    summaries = [a.get("summary", "") for a in s["context_articles"] if a.get("summary")]
                    with st.spinner("Генерируем прогноз с помощью LLM..."):
                        forecast = generate_signal_forecast(s["signal"], summaries)
                    glass_card(f"<b>🔮 Прогноз для «{s['signal']}»:</b><br><br>{forecast.replace(chr(10), '<br>')}", accent=True)
    else:
        st.info("Слабых сигналов пока не обнаружено. Нужно больше проанализированных статей.")



# ═══════════════════════════════════════════════════════════════
# PAGE: ПОИСК
# ═══════════════════════════════════════════════════════════════
elif page == "Поиск":
    neon_header("🔍 Гибридный поиск", 1)
    st.caption("Семантический + полнотекстовый поиск по проанализированным статьям")

    query = st.text_input("Поисковый запрос", placeholder="Введите тему...")
    sc1, sc2 = st.columns(2)
    with sc1:
        top_k = st.slider("Результатов", 5, 50, 20)
    with sc2:
        vec_w = st.slider("Вес семантики", 0.0, 1.0, 0.6, 0.1)

    if query:
        from src.nlp.openrouter import OpenRouterProvider
        from src.services.search_service import hybrid_search
        with st.spinner("Ищем..."):
            provider = OpenRouterProvider()
            q_emb = provider.embed(query)
            results = hybrid_search(query, q_emb, top_k=top_k, vector_weight=vec_w, fts_weight=1.0 - vec_w)
        if results:
            st.success(f"Найдено {len(results)} результатов")
            for r in results:
                with st.expander(f"[{r['source'].upper()}] {r['title']} ({r['combined_score']:.3f})"):
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("Семантика", f"{r['vec_score']:.3f}")
                    rc2.metric("Текст", f"{r['fts_score']:.3f}")
                    if r.get("sentiment") is not None:
                        rc3.metric("Сентимент", f"{r['sentiment']:+.2f}")
                    st.write(r["summary"])
                    if r["entities"]:
                        st.json(r["entities"])
                    st.markdown(f"[Читать оригинал]({r['link']})")
        else:
            st.warning("Ничего не найдено.")


# ═══════════════════════════════════════════════════════════════
# PAGE: ТРЕНДЫ
# ═══════════════════════════════════════════════════════════════
elif page == "Тренды":
    neon_header("📈 Тренды и скорость упоминаний", 1)

    from src.services.trend_service import compute_trend_velocity, get_entity_timeline

    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        t_window = st.selectbox("Окно (дни)", [3, 7, 14], index=1)
    with tc2:
        t_compare = st.selectbox("Сравнение (дни)", [7, 14, 30], index=0)
    with tc3:
        t_min = st.number_input("Мин. упоминаний", 1, 20, 3)

    trends = compute_trend_velocity(window_days=t_window, compare_days=t_compare, min_mentions=t_min)
    if trends:
        neon_header("🚀 Растущие тренды", 3)
        rising = [t for t in trends if t["velocity"] > 0][:20]
        if rising:
            df_r = pd.DataFrame(rising)
            fig = px.bar(df_r, x="velocity", y="entity", color="category", orientation="h",
                         labels={"velocity": "Скорость", "entity": "", "category": "Категория"},
                         title=f"Ускорение ({t_window}д vs предыдущие {t_compare}д)")
            fig.update_layout(**PLOTLY_LAYOUT, height=max(300, len(rising) * 30), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

        neon_header("📊 Таймлайн сущности", 3)
        ent_name = st.text_input("Имя сущности", placeholder="GPT-4, Yandex...")
        if ent_name:
            tl = get_entity_timeline(ent_name, days=30)
            if tl:
                fig = px.bar(pd.DataFrame(tl), x="date", y="count",
                             title=f"Упоминания «{ent_name}» за 30 дней",
                             labels={"count": "Упоминания", "date": "Дата"})
                fig.update_layout(**PLOTLY_LAYOUT, height=300)
                fig.update_traces(marker_color="#a78bfa")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(f"«{ent_name}» не найден.")

        neon_header("📋 Все тренды", 3)
        st.dataframe(pd.DataFrame(trends[:50]), use_container_width=True, hide_index=True)
    else:
        st.info("Недостаточно данных для анализа трендов.")


# ═══════════════════════════════════════════════════════════════
# PAGE: СЕМАНТИЧЕСКАЯ КАРТА
# ═══════════════════════════════════════════════════════════════
elif page == "Семантическая карта":
    neon_header("🗺️ Семантическая карта статей", 1)
    st.caption("2D-проекция эмбеддингов (UMAP/PCA) с кластеризацией")

    mc1, mc2 = st.columns(2)
    with mc1:
        map_days = st.selectbox("Период", [3, 7, 14, 30], index=1)
    with mc2:
        n_neigh = st.slider("UMAP n_neighbors", 5, 50, 15)

    if st.button("Построить карту", type="primary"):
        from src.services.semantic_map_service import compute_semantic_map
        with st.spinner("Вычисляем проекцию..."):
            result = compute_semantic_map(days=map_days, n_neighbors=n_neigh)
        if result["points"]:
            df = pd.DataFrame(result["points"])
            fig = px.scatter(df, x="x", y="y", color="cluster", symbol="source",
                             hover_data=["title", "source", "sentiment"],
                             title=f"{len(df)} статей, {result['n_clusters']} кластеров",
                             labels={"x": "UMAP-1", "y": "UMAP-2", "cluster": "Кластер"})
            fig.update_layout(**PLOTLY_LAYOUT, height=700)
            fig.update_traces(marker=dict(size=7, opacity=0.75))
            st.plotly_chart(fig, use_container_width=True)

            neon_header("📦 Кластеры", 3)
            for cid in sorted(df["cluster"].unique()):
                cdf = df[df["cluster"] == cid]
                with st.expander(f"Кластер {cid} ({len(cdf)} статей)"):
                    for _, row in cdf.head(10).iterrows():
                        st.write(f"• [{row['source'].upper()}] {row['title']}")
        else:
            st.warning("Мало статей с эмбеддингами (нужно >= 5).")


# ═══════════════════════════════════════════════════════════════
# PAGE: ДАЙДЖЕСТЫ
# ═══════════════════════════════════════════════════════════════
elif page == "Дайджесты":
    neon_header("📰 Ежедневные дайджесты", 1)

    ses = get_session()
    try:
        digests = ses.execute(
            select(DailyDigest).where(DailyDigest.source == "all")
            .order_by(DailyDigest.digest_date.desc()).limit(30)
        ).scalars().all()
    finally:
        ses.close()

    if not digests:
        st.info("Дайджестов пока нет. Генерируйте их в админ-панели или через Celery Beat.")
    else:
        for d in digests:
            ds = d.digest_date.strftime("%d.%m.%Y") if d.digest_date else "?"
            sent = f" | Настроение: {d.avg_sentiment:+.2f}" if d.avg_sentiment is not None else ""
            with st.expander(f"📰 {ds} — {d.article_count} статей{sent}"):
                st.markdown(d.narrative)
                if d.top_entities:
                    st.markdown("**Топ сущности:**")
                    st.json(d.top_entities)



# ═══════════════════════════════════════════════════════════════
# PAGE: АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════════
elif page == "Админ-панель":
    neon_header("⚙️ Админ-панель", 1)

    if not st.session_state.is_admin:
        st.warning("Войдите через боковую панель для доступа.")
        st.stop()

    tab_ov, tab_ing, tab_an, tab_tg, tab_dig, tab_src, tab_runs = st.tabs(
        ["Обзор", "Сбор", "Анализ", "Telegram-каналы", "Дайджесты", "Источники", "Запуски"]
    )

    with tab_ov:
        counts = _status_counts()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("PENDING", counts.get("PENDING", 0))
        c2.metric("QUEUED", counts.get("QUEUED_FOR_ANALYSIS", 0))
        c3.metric("ANALYZED", counts.get("ANALYZED", 0))
        c4.metric("Всего", sum(counts.values()))

        day_df = _articles_per_day()
        if not day_df.empty:
            neon_header("📊 Статьи по дням", 3)
            pivot = day_df.pivot_table(index="day", columns="source", values="cnt", fill_value=0, aggfunc="sum")
            pivot = pivot.sort_index(ascending=False)
            pivot["TOTAL"] = pivot.sum(axis=1)
            st.dataframe(pivot.reset_index().rename(columns={"day": "Дата"}), use_container_width=True, hide_index=True)

            chart_p = day_df.pivot_table(index="day", columns="source", values="cnt", fill_value=0, aggfunc="sum").sort_index()
            melted = chart_p.reset_index().melt(id_vars="day", var_name="source", value_name="count")
            fig = px.bar(melted, x="day", y="count", color="source", barmode="group",
                         labels={"count": "Количество", "day": "Дата", "source": "Источник"})
            fig.update_layout(**PLOTLY_LAYOUT, height=350)
            st.plotly_chart(fig, use_container_width=True)

            today_d = date.today()
            yesterday_d = today_d - timedelta(days=1)
            t_total = int(pivot.loc[today_d, "TOTAL"]) if today_d in pivot.index else 0
            y_total = int(pivot.loc[yesterday_d, "TOTAL"]) if yesterday_d in pivot.index else 0
            sc1, sc2 = st.columns(2)
            sc1.metric(f"Сегодня ({today_d})", f"{t_total} статей")
            sc2.metric(f"Вчера ({yesterday_d})", f"{y_total} статей")

        from src.services.ingestion_service import get_db_date_coverage
        cov = get_db_date_coverage()
        if cov["total"] > 0:
            cv1, cv2 = st.columns(2)
            cv1.metric("Самая ранняя", str(cov["min_date"].date()) if cov["min_date"] else "—")
            cv2.metric("Самая поздняя", str(cov["max_date"].date()) if cov["max_date"] else "—")

        neon_header("💰 Оценка стоимости", 3)
        pend = _pending_tokens()
        tt = pend["total_tokens"]
        est_llm = (tt / 1_000_000) * (settings.llm_input_cost_per_1m + settings.llm_output_cost_per_1m * 0.15)
        est_emb = (tt / 1_000_000) * settings.embedding_cost_per_1m
        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("Ожидающих", pend["count"])
        cc2.metric("Токенов", f"{tt:,}")
        cc3.metric("LLM $", f"${est_llm:.4f}")
        cc4.metric("Итого $", f"${est_llm + est_emb:.4f}")

    with tab_ing:
        neon_header("📥 Сбор статей", 3)
        preset = st.selectbox("Период", ["Вчера + сегодня", "Последние 3 дня", "Последние 7 дней",
                                          "Последние 30 дней", "Произвольный"], key="i_pre")
        today = date.today()
        if preset == "Произвольный":
            ic1, ic2 = st.columns(2)
            with ic1:
                i_since = st.date_input("С", value=today - timedelta(days=1), key="i_since")
            with ic2:
                i_until = st.date_input("По", value=today, key="i_until")
        else:
            dm = {"Вчера + сегодня": 1, "Последние 3 дня": 3, "Последние 7 дней": 7, "Последние 30 дней": 30}
            i_since = today - timedelta(days=dm[preset])
            i_until = today

        from src.scrapers.registry import get_all_sources
        all_src = get_all_sources()
        sel_src = st.multiselect("Источники", list(all_src.keys()), default=list(all_src.keys()),
                                 format_func=lambda x: f"{all_src[x].icon} {all_src[x].description}")
        st.caption(f"Период: **{i_since}** — **{i_until}** (UTC)")

        if st.button("Запустить сбор", type="primary", key="run_ing"):
            s_dt = datetime.combine(i_since, datetime.min.time(), tzinfo=timezone.utc)
            u_dt = datetime.combine(i_until, datetime.max.time(), tzinfo=timezone.utc)
            with st.spinner(f"Собираем статьи..."):
                from src.services.ingestion_service import ingest_all
                stats = ingest_all(since=s_dt, until=u_dt, sources=sel_src)
            st.success(f"Готово! Найдено {stats['total_fetched']}, новых {stats['new']}, авто-очередь {stats['queued']}, в БД {stats['skipped']}")
            st.rerun()

    with tab_an:
        neon_header("🧠 Анализ статей", 3)
        a_pre = st.selectbox("Период", ["Вчера + сегодня", "Последние 3 дня", "Последние 7 дней",
                                         "Последние 30 дней", "Произвольный"], key="a_pre")
        if a_pre == "Произвольный":
            ac1, ac2 = st.columns(2)
            with ac1:
                a_since = st.date_input("С", value=today - timedelta(days=1), key="a_since")
            with ac2:
                a_until = st.date_input("По", value=today, key="a_until")
        else:
            adm = {"Вчера + сегодня": 1, "Последние 3 дня": 3, "Последние 7 дней": 7, "Последние 30 дней": 30}
            a_since = today - timedelta(days=adm[a_pre])
            a_until = today

        a_scope = st.selectbox("Область", ["QUEUED + PENDING", "Только QUEUED", "Только PENDING"], key="a_scope")
        scope_m = {"QUEUED + PENDING": ["QUEUED_FOR_ANALYSIS", "PENDING"],
                   "Только QUEUED": ["QUEUED_FOR_ANALYSIS"], "Только PENDING": ["PENDING"]}

        as_dt = datetime.combine(a_since, datetime.min.time(), tzinfo=timezone.utc)
        au_dt = datetime.combine(a_until, datetime.max.time(), tzinfo=timezone.utc)
        ses = get_session()
        try:
            sconds = [Article.status == s for s in scope_m[a_scope]]
            pcount = ses.execute(select(func.count(Article.id)).where(
                and_(or_(*sconds), Article.published_at >= as_dt, Article.published_at <= au_dt)
            )).scalar()
        finally:
            ses.close()

        st.info(f"Статей к анализу: **{pcount}**")
        if st.button("Запустить анализ", type="primary", key="run_an"):
            with st.spinner(f"Анализируем {pcount} статей..."):
                from src.nlp.openrouter import OpenRouterProvider
                from src.services.analysis_service import analyze_by_date_range
                n = analyze_by_date_range(OpenRouterProvider(), since=as_dt, until=au_dt, statuses=scope_m[a_scope])
            st.success(f"Проанализировано {n} / {pcount} статей.")
            st.rerun()

    with tab_tg:
        neon_header("💬 Telegram-каналы", 3)
        st.caption("Добавьте публичные Telegram-каналы для мониторинга. Посты будут собираться автоматически каждые 15 минут.")

        # Show existing channels
        ses_tg = get_session()
        try:
            channels = ses_tg.execute(
                select(TelegramChannel).order_by(TelegramChannel.created_at.desc())
            ).scalars().all()
        finally:
            ses_tg.close()

        if channels:
            neon_header("📋 Подключённые каналы", 3)
            for ch in channels:
                status_icon = "🟢" if ch.enabled else "🔴"
                last_fetch = ch.last_fetched_at.strftime("%d.%m %H:%M") if ch.last_fetched_at else "никогда"
                with st.expander(f"{status_icon} @{ch.username} — {ch.title or '?'} | Постов: {ch.post_count} | Посл. сбор: {last_fetch}"):
                    tc1, tc2, tc3 = st.columns(3)
                    tc1.write(f"**Канал:** [@{ch.username}](https://t.me/{ch.username})")
                    tc2.write(f"**Добавлен:** {ch.created_at.strftime('%d.%m.%Y %H:%M')}")
                    tc3.write(f"**Статус:** {'Включён' if ch.enabled else 'Выключен'}")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if ch.enabled:
                            if st.button(f"⏸ Выключить", key=f"disable_{ch.username}"):
                                ses2 = get_session()
                                try:
                                    ses2.execute(text(
                                        "UPDATE telegram_channels SET enabled = FALSE WHERE username = :u"
                                    ), {"u": ch.username})
                                    ses2.commit()
                                finally:
                                    ses2.close()
                                from src.scrapers.registry import reload_all_sources
                                reload_all_sources()
                                st.rerun()
                        else:
                            if st.button(f"▶ Включить", key=f"enable_{ch.username}"):
                                ses2 = get_session()
                                try:
                                    ses2.execute(text(
                                        "UPDATE telegram_channels SET enabled = TRUE WHERE username = :u"
                                    ), {"u": ch.username})
                                    ses2.commit()
                                finally:
                                    ses2.close()
                                from src.scrapers.registry import reload_all_sources
                                reload_all_sources()
                                st.rerun()
                    with bc2:
                        if st.button(f"🗑 Удалить", key=f"del_{ch.username}"):
                            ses2 = get_session()
                            try:
                                ses2.execute(text(
                                    "DELETE FROM telegram_channels WHERE username = :u"
                                ), {"u": ch.username})
                                ses2.commit()
                            finally:
                                ses2.close()
                            from src.scrapers.registry import reload_all_sources
                            reload_all_sources()
                            st.rerun()

        st.markdown("---")
        neon_header("➕ Добавить канал", 3)

        new_channel = st.text_input(
            "Ссылка на канал или @username",
            placeholder="https://t.me/russicaRU или @ejdailyru",
            key="new_tg_channel",
        )

        if st.button("Тестировать и добавить", type="primary", key="add_tg"):
            if new_channel:
                import re as _re
                # Extract username from URL or @mention
                channel_input = new_channel.strip()
                m = _re.search(r"t\.me/(\w+)", channel_input)
                if m:
                    username = m.group(1)
                elif channel_input.startswith("@"):
                    username = channel_input.lstrip("@")
                else:
                    username = channel_input

                with st.spinner(f"Тестируем канал @{username}..."):
                    from src.scrapers.telegram_channel import test_channel
                    result = test_channel(username)

                if result["ok"]:
                    # Save to DB
                    ses2 = get_session()
                    try:
                        from sqlalchemy.dialects.postgresql import insert as pg_insert
                        stmt = (
                            pg_insert(TelegramChannel)
                            .values(
                                username=username,
                                title=result["title"],
                                enabled=True,
                                post_count=result["post_count"],
                            )
                            .on_conflict_do_update(
                                constraint="uq_tg_channel_username",
                                set_={"title": result["title"], "enabled": True},
                            )
                        )
                        ses2.execute(stmt)
                        ses2.commit()
                    finally:
                        ses2.close()

                    # Reload registry
                    from src.scrapers.registry import reload_all_sources
                    reload_all_sources()

                    st.success(
                        f"✅ Канал @{username} добавлен!\n\n"
                        f"**Название:** {result['title']}\n"
                        f"**Постов за 7 дней:** {result['post_count']}\n"
                        f"**Последний пост:** {result['latest_post'][:80]}"
                    )
                    st.rerun()
                else:
                    st.error(f"❌ Ошибка: {result['error']}")
            else:
                st.warning("Введите ссылку на канал")

    with tab_dig:
        neon_header("📰 Генерация дайджеста", 3)
        dig_date = st.date_input("Дата", value=today - timedelta(days=1), key="dig_d")
        if st.button("Сгенерировать", type="primary", key="run_dig"):
            from src.services.digest_service import build_daily_digest
            with st.spinner(f"Генерируем дайджест за {dig_date}..."):
                res = build_daily_digest(dig_date)
            if res["narrative"]:
                st.success(f"Готово: {res['article_count']} статей")
                st.markdown(res["narrative"])
            else:
                st.warning("Нет проанализированных статей за эту дату.")

    with tab_src:
        neon_header("📡 Источники", 3)
        from src.scrapers.registry import get_all_sources
        for name, cfg in get_all_sources().items():
            with st.expander(f"{cfg.icon} {name} — {'вкл' if cfg.enabled else 'выкл'}"):
                st.write(f"**{cfg.description}**")
                st.write(f"Интервал: {cfg.poll_interval_minutes} мин | Класс: `{cfg.scraper_class.__name__}`")

    with tab_runs:
        neon_header("📜 История запусков", 3)
        ses = get_session()
        try:
            runs = ses.execute(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(30)).scalars().all()
        finally:
            ses.close()
        if runs:
            rrows = [{
                "Источник": r.source, "Период": f"{r.since.strftime('%d.%m')}—{r.until.strftime('%d.%m')}",
                "Статус": r.status, "Найдено": r.total_fetched, "Новых": r.new_articles,
                "Начало": r.started_at.strftime("%d.%m %H:%M") if r.started_at else "",
                "Ошибка": (r.error_message or "")[:80],
            } for r in runs]
            st.dataframe(pd.DataFrame(rrows), use_container_width=True, hide_index=True)
        else:
            st.info("Запусков пока не было.")

    # Recent articles
    st.markdown("---")
    neon_header("📋 Последние статьи", 3)
    ses = get_session()
    try:
        all_art = ses.execute(select(Article).order_by(Article.published_at.desc().nullslast()).limit(100)).scalars().all()
    finally:
        ses.close()
    if all_art:
        st.dataframe(pd.DataFrame([{
            "Источник": a.source, "Статус": a.status, "Заголовок": a.title[:80],
            "Токены": a.estimated_tokens, "Теги": ", ".join(a.native_tags or [])[:80],
            "Опубликовано": str(a.published_at or ""),
        } for a in all_art]), use_container_width=True, hide_index=True)

