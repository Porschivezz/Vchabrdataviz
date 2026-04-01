"""Abstract base class for all scrapers."""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from datetime import datetime


@dataclasses.dataclass
class RawArticle:
    """Transport object returned by every scraper."""
    source: str
    title: str
    link: str
    published_at: datetime | None
    raw_text: str
    native_tags: list[str]


class BaseScraper(ABC):
    """Every concrete scraper must implement ``fetch_articles``."""

    @abstractmethod
    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        """Return all articles published in [since, until].

        The scraper must paginate backwards until it reaches articles older
        than ``since``, then stop.  Articles outside the range are discarded.
        """
        ...
