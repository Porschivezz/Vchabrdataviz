"""Entry point for the RU News Collector microservice.

Starts:
1. APScheduler for periodic news collection
2. FastAPI/Uvicorn for the sync API

Usage:
    python -m ru_collector.main
"""

from __future__ import annotations

import logging
import sys

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler

from ru_collector.api.app import app
from ru_collector.collector import collect_all
from ru_collector.config import settings
from ru_collector.db.engine import engine
from ru_collector.db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured")


def start_scheduler() -> BackgroundScheduler:
    """Start the periodic collection scheduler."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        collect_all,
        "interval",
        minutes=settings.poll_interval_minutes,
        id="collect_all",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: collecting every %d minutes",
        settings.poll_interval_minutes,
    )
    return scheduler


def main() -> None:
    logger.info("=== RU News Collector starting ===")

    init_db()

    # Run initial collection
    if "--skip-initial" not in sys.argv:
        logger.info("Running initial collection...")
        try:
            results = collect_all()
            for src, count in sorted(results.items()):
                status = f"{count} new" if count >= 0 else "FAILED"
                logger.info("  %s: %s", src, status)
        except Exception:
            logger.exception("Initial collection failed")

    scheduler = start_scheduler()

    try:
        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_level="info",
        )
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
