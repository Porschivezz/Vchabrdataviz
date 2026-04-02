"""Telegram bot for Пульс Рунета — sends digests, pulse reports, and allows queries."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.core.config import settings

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📡 Привет! Я бот Пульс Рунета.\n\n"
        "Команды:\n"
        "/digest — дайджест за вчера\n"
        "/trends — горячие тренды\n"
        "/drama — самые полярные темы\n"
        "/signals — слабые сигналы (радар будущего)\n"
        "/pulse <тема> — досье на тему/компанию\n"
        "/stats — статистика базы\n"
        "/search <запрос> — поиск по статьям\n"
        "/wrapped — недельная сводка инсайдера\n"
    )


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send yesterday's digest."""
    from src.core.database import get_session
    from src.core.models import DailyDigest
    from sqlalchemy import select

    yesterday = date.today() - timedelta(days=1)
    session = get_session()
    try:
        digest = session.execute(
            select(DailyDigest).where(
                DailyDigest.digest_date == datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc),
                DailyDigest.source == "all",
            )
        ).scalars().first()

        if digest:
            text = (
                f"📰 Дайджест за {yesterday}\n"
                f"Статей: {digest.article_count}\n"
            )
            if digest.avg_sentiment is not None:
                emoji = "😊" if digest.avg_sentiment > 0.1 else "😐" if digest.avg_sentiment > -0.1 else "😟"
                text += f"Настроение: {emoji} ({digest.avg_sentiment:+.2f})\n"
            text += f"\n{digest.narrative}"

            if len(text) > 4000:
                text = text[:4000] + "..."
            await update.message.reply_text(text)
        else:
            await update.message.reply_text(f"Дайджест за {yesterday} пока не готов.")
    finally:
        session.close()


async def cmd_trends(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show trending entities."""
    from src.services.trend_service import compute_trend_velocity

    trends = compute_trend_velocity(window_days=3, compare_days=7, min_mentions=2)
    if not trends:
        await update.message.reply_text("Пока нет данных о трендах.")
        return

    lines = ["🔥 Горячие тренды (3 дня vs предыдущие 7):\n"]
    for t in trends[:15]:
        arrow = "🟢" if t["velocity"] > 0.5 else "🟡" if t["velocity"] > 0 else "🔴"
        lines.append(
            f"{arrow} {t['entity']} — {t['current']} упом. "
            f"(×{t['velocity']:+.1f})"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_drama(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show most polarized topics."""
    from src.services.polarization_service import detect_polarized_topics

    topics = detect_polarized_topics(days=3, min_articles=3, top_n=10)
    if not topics:
        await update.message.reply_text("Нет достаточно данных для детектора драмы.")
        return

    lines = ["⚡ Детектор Драмы — самые полярные темы:\n"]
    for t in topics[:8]:
        sources_str = " vs ".join(
            f"{src}({d['avg_sentiment']:+.1f})"
            for src, d in t["sources"].items()
        )
        lines.append(
            f"🎭 {t['entity']} [{t['article_count']} статей]\n"
            f"   Разлом: {t['divergence']:.2f} | {sources_str}"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_signals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show weak signals."""
    from src.services.weak_signal_service import detect_weak_signals

    signals = detect_weak_signals(days=14, max_mentions=8, min_mentions=2)
    if not signals:
        await update.message.reply_text("Слабых сигналов пока не обнаружено.")
        return

    lines = ["🔮 Радар Будущего — слабые сигналы:\n"]
    for s in signals[:10]:
        dist = "●" if s["recency_score"] > 0.7 else "◐" if s["recency_score"] > 0.3 else "○"
        hype = "🔥" if s["avg_hype"] > 0.6 else "✨" if s["avg_hype"] > 0.3 else "💡"
        lines.append(
            f"{dist} {hype} {s['signal']} [{s['mentions']}x]\n"
            f"   Хайп: {s['avg_hype']:.1f} | С: {s['first_seen']}"
        )

    lines.append("\n📌 /pulse <сигнал> — прогноз по сигналу")
    await update.message.reply_text("\n".join(lines))


async def cmd_pulse(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a data portrait for a topic/entity."""
    topic = " ".join(ctx.args) if ctx.args else ""
    if not topic:
        await update.message.reply_text(
            "Использование: /pulse <тема или компания>\n"
            "Пример: /pulse Яндекс"
        )
        return

    await update.message.reply_text(f"🔍 Собираю досье на «{topic}»...")

    from src.services.knowledge_graph_service import get_entity_context
    from src.services.trend_service import get_entity_timeline

    # Get recent articles and relations
    context = get_entity_context(topic, days=14, limit=10)
    timeline = get_entity_timeline(topic, days=14)

    if not context:
        await update.message.reply_text(f"«{topic}» не найден в базе за последние 14 дней.")
        return

    # Build portrait
    sentiments = [c["sentiment"] for c in context if c["sentiment"] is not None]
    avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0.0
    hypes = [c["hype_score"] for c in context if c["hype_score"] is not None]
    avg_hype = sum(hypes) / len(hypes) if hypes else 0.0
    sources = set(c["source"] for c in context)

    # Sentiment emoji bar
    if avg_sent > 0.3:
        sent_bar = "🟩🟩🟩"
    elif avg_sent > 0.0:
        sent_bar = "🟩🟩⬜"
    elif avg_sent > -0.3:
        sent_bar = "🟨🟨⬜"
    else:
        sent_bar = "🟥🟥🟥"

    # Hype gauge
    hype_pct = int(avg_hype * 100)
    hype_bar = "█" * (hype_pct // 10) + "░" * (10 - hype_pct // 10)

    lines = [
        f"📊 ПУЛЬС: {topic.upper()}",
        f"{'═' * 30}",
        f"",
        f"📰 Упоминаний: {len(context)} за 14 дней",
        f"📡 Источники: {', '.join(s.upper() for s in sources)}",
        f"",
        f"💭 Настроение: {sent_bar} ({avg_sent:+.2f})",
        f"🔥 Хайп:      [{hype_bar}] {hype_pct}%",
        f"",
    ]

    # Relations
    all_relations = []
    for c in context:
        all_relations.extend(c.get("relations", []))

    if all_relations:
        lines.append("🔗 Ключевые связи:")
        seen = set()
        for r in all_relations[:5]:
            key = f"{r['subject']}→{r['object']}"
            if key not in seen:
                seen.add(key)
                lines.append(f"   {r['subject']} → {r['predicate']} → {r['object']}")
        lines.append("")

    # Timeline sparkline
    if timeline:
        max_count = max(t["count"] for t in timeline)
        sparkline = ""
        for t in timeline[-14:]:
            ratio = t["count"] / max_count if max_count > 0 else 0
            if ratio > 0.75:
                sparkline += "▇"
            elif ratio > 0.5:
                sparkline += "▆"
            elif ratio > 0.25:
                sparkline += "▃"
            elif ratio > 0:
                sparkline += "▁"
            else:
                sparkline += " "
        lines.append(f"📈 14 дней: [{sparkline}]")
        lines.append("")

    # Latest headlines
    lines.append("📌 Последние:")
    for c in context[:3]:
        lines.append(f"  • {c['title'][:60]}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "..."
    await update.message.reply_text(text, parse_mode=None)


async def cmd_wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a weekly insider wrap-up."""
    await update.message.reply_text("📦 Генерирую недельную сводку...")

    from src.services.trend_service import compute_trend_velocity
    from src.services.weak_signal_service import detect_weak_signals
    from src.services.ingestion_service import get_db_date_coverage

    coverage = get_db_date_coverage()
    trends = compute_trend_velocity(window_days=7, compare_days=7, min_mentions=3)
    signals = detect_weak_signals(days=7, max_mentions=8, min_mentions=2)

    lines = [
        "📦 RUNET WRAPPED — Неделя в цифрах",
        "═" * 35,
        "",
        f"📰 Статей в базе: {coverage['total']}",
    ]

    if coverage["per_source"]:
        for src, cnt in coverage["per_source"].items():
            lines.append(f"   {src.upper()}: {cnt}")
    lines.append("")

    if trends:
        lines.append("🚀 Тренды недели:")
        for t in trends[:5]:
            emoji = "🟢" if t["velocity"] > 0 else "🔴"
            lines.append(f"   {emoji} {t['entity']} (×{t['velocity']:+.1f}, {t['current']} упом.)")
        lines.append("")

    if signals:
        lines.append("🔮 Что вы могли пропустить:")
        for s in signals[:3]:
            lines.append(f"   💡 {s['signal']} — {s['mentions']} упоминаний, хайп {s['avg_hype']:.1f}")
        lines.append("")

    lines.append("📡 Пульс Рунета — видеть раньше остальных")

    text = "\n".join(lines)
    await update.message.reply_text(text)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show database stats."""
    from src.services.ingestion_service import get_db_date_coverage

    coverage = get_db_date_coverage()
    text = (
        f"📊 Статистика базы:\n"
        f"Всего статей: {coverage['total']}\n"
    )
    if coverage["per_source"]:
        for src, cnt in coverage["per_source"].items():
            text += f"  • {src}: {cnt}\n"
    if coverage["min_date"]:
        text += f"Период: {coverage['min_date'].date()} — {coverage['max_date'].date()}"

    await update.message.reply_text(text)


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Semantic search via bot."""
    query = " ".join(ctx.args) if ctx.args else ""
    if not query:
        await update.message.reply_text("Использование: /search <запрос>")
        return

    from src.nlp.openrouter import OpenRouterProvider
    from src.services.search_service import hybrid_search

    provider = OpenRouterProvider()
    embedding = provider.embed(query)
    results = hybrid_search(query, embedding, top_k=5)

    if not results:
        await update.message.reply_text("Ничего не найдено.")
        return

    lines = [f"🔍 Результаты по «{query}»:\n"]
    for r in results:
        sentiment_str = ""
        if r.get("sentiment") is not None:
            sentiment_str = f" | сент: {r['sentiment']:+.2f}"
        lines.append(
            f"• [{r['source'].upper()}] {r['title'][:60]}\n"
            f"  Релевантность: {r['combined_score']:.2f}{sentiment_str}\n"
            f"  {r['link']}"
        )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "..."
    await update.message.reply_text(text)


def run_bot() -> None:
    """Start the Telegram bot (blocking)."""
    token = settings.telegram_bot_token
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set, bot will not start")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CommandHandler("drama", cmd_drama))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("pulse", cmd_pulse))
    app.add_handler(CommandHandler("wrapped", cmd_wrapped))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("search", cmd_search))

    logger.info("Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bot()
