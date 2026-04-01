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
    poll_interval_minutes: int = 30
    description: str = ""
    icon: str = ""
    extra: dict = field(default_factory=dict)


# Global registry
_registry: dict[str, SourceConfig] = {}


def register_source(config: SourceConfig) -> None:
    """Register a source plugin."""
    _registry[config.name] = config
    logger.info("Registered source: %s (enabled=%s)", config.name, config.enabled)


def get_source(name: str) -> SourceConfig | None:
    """Get a source config by name."""
    return _registry.get(name)


def get_all_sources() -> dict[str, SourceConfig]:
    """Return all registered sources."""
    return dict(_registry)


def get_enabled_sources() -> dict[str, SourceConfig]:
    """Return only enabled sources."""
    return {k: v for k, v in _registry.items() if v.enabled}


def _init_default_sources() -> None:
    """Register built-in sources (Habr, VC.ru)."""
    from src.scrapers.habr import HabrScraper
    from src.scrapers.vc import VcScraper

    register_source(SourceConfig(
        name="habr",
        scraper_class=HabrScraper,
        enabled=True,
        poll_interval_minutes=30,
        description="Habr.com — технические статьи и новости",
        icon="📝",
    ))
    register_source(SourceConfig(
        name="vc",
        scraper_class=VcScraper,
        enabled=True,
        poll_interval_minutes=30,
        description="VC.ru — бизнес и технологии",
        icon="💼",
    ))


# Auto-register on import
_init_default_sources()
