"""Telegram bot for Пульс Рунета — sends digests and allows queries."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.core.config import settings

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот Пульс Рунета.\n\n"
        "Команды:\n"
        "/digest — дайджест за вчера\n"
        "/trends — горячие тренды\n"
        "/stats — статистика базы\n"
        "/search <запрос> — поиск по статьям\n"
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

            # Telegram message limit is 4096 chars
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
            f"{arrow} {t['entity']} — {t['current']} упоминаний "
            f"(×{t['velocity']:+.1f})"
        )

    await update.message.reply_text("\n".join(lines))


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
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("search", cmd_search))

    logger.info("Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bot()
