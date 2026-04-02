"""Source plugin registry — central place to manage all scrapers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Type

from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


@dataclass
class SourceConfig:
    """Configuration for a single scraping source."""
    name: str
    scraper_class: Type[BaseScraper]
    enabled: bool = True
    poll_interval_minutes: int = 15
    description: str = ""
    icon: str = ""
    extra: dict = field(default_factory=dict)


# Global registry
_registry: dict[str, SourceConfig] = {}


def register_source(config: SourceConfig) -> None:
    """Register a source plugin."""
    _registry[config.name] = config
    logger.info("Registered source: %s (enabled=%s)", config.name, config.enabled)


def unregister_source(name: str) -> None:
    """Remove a source from registry."""
    _registry.pop(name, None)


def get_source(name: str) -> SourceConfig | None:
    return _registry.get(name)


def get_all_sources() -> dict[str, SourceConfig]:
    return dict(_registry)


def get_enabled_sources() -> dict[str, SourceConfig]:
    return {k: v for k, v in _registry.items() if v.enabled}


def _init_default_sources() -> None:
    """Register built-in sources (Habr, VC.ru)."""
    from src.scrapers.habr import HabrScraper
    from src.scrapers.vc import VcScraper

    register_source(SourceConfig(
        name="habr",
        scraper_class=HabrScraper,
        enabled=True,
        poll_interval_minutes=15,
        description="Habr.com — технические статьи и новости",
        icon="📝",
    ))
    register_source(SourceConfig(
        name="vc",
        scraper_class=VcScraper,
        enabled=True,
        poll_interval_minutes=15,
        description="VC.ru — бизнес и технологии",
        icon="💼",
    ))


def load_telegram_channels_from_db() -> None:
    """Load all enabled Telegram channels from DB and register them."""
    from src.core.database import get_session
    from src.core.models import TelegramChannel
    from src.scrapers.telegram_channel import TelegramChannelScraper
    from sqlalchemy import select

    session = get_session()
    try:
        channels = session.execute(
            select(TelegramChannel).where(TelegramChannel.enabled == True)
        ).scalars().all()

        for ch in channels:
            source_name = f"tg_{ch.username}"
            # Create a factory that captures the username
            username = ch.username

            class _TgScraper(TelegramChannelScraper):
                def __init__(self):
                    super().__init__(channel_username=username)

            register_source(SourceConfig(
                name=source_name,
                scraper_class=_TgScraper,
                enabled=True,
                poll_interval_minutes=15,
                description=f"Telegram: @{ch.username}" + (f" ({ch.title})" if ch.title else ""),
                icon="💬",
                extra={"telegram_channel": ch.username},
            ))

        if channels:
            logger.info("Loaded %d Telegram channels from DB", len(channels))
    except Exception as exc:
        logger.warning("Could not load TG channels from DB: %s", exc)
    finally:
        session.close()


def reload_all_sources() -> None:
    """Reload all sources: built-in + Telegram channels from DB."""
    _registry.clear()
    _init_default_sources()
    load_telegram_channels_from_db()


# Auto-register on import
_init_default_sources()
# Try to load TG channels (may fail if DB not ready yet)
try:
    load_telegram_channels_from_db()
except Exception:
    pass
