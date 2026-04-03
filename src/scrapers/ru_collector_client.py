"""Client for the RU News Collector API (running on Russian VPS).

Pulls pending articles from the RU collector and stores them
in the main app's database via the existing pipeline.

Configure via environment:
    RU_COLLECTOR_URL=http://<ru-vps-ip>:8100
    RU_COLLECTOR_TOKEN=<shared-api-token>
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from src.core.config import settings
from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)


class RuCollectorClient(BaseScraper):
    """Pulls pre-collected articles from the RU collector API."""

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        self.base_url = getattr(settings, "ru_collector_url", "").rstrip("/")
        self.token = getattr(settings, "ru_collector_token", "")

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        if not self.base_url or not self.token:
            logger.warning("RU Collector not configured (RU_COLLECTOR_URL / RU_COLLECTOR_TOKEN)")
            return []

        url = f"{self.base_url}/api/articles/pending"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout, params={"limit": 2000})
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Failed to fetch from RU Collector: %s", exc)
            return []

        data = resp.json()
        articles_data = data.get("articles", [])
        logger.info("RU Collector: received %d pending articles", len(articles_data))

        articles: list[RawArticle] = []
        ids_to_ack: list[int] = []

        for item in articles_data:
            pub_dt = None
            if item.get("published_at"):
                try:
                    pub_dt = datetime.fromisoformat(item["published_at"])
                except ValueError:
                    pass

            articles.append(RawArticle(
                source=item.get("source", "unknown"),
                title=item.get("title", ""),
                link=item.get("link", ""),
                published_at=pub_dt,
                raw_text=item.get("raw_text", ""),
                native_tags=item.get("tags", []),
            ))
            if "id" in item:
                ids_to_ack.append(item["id"])

        # Acknowledge received articles
        if ids_to_ack:
            self._ack_articles(ids_to_ack, headers)

        return articles

    def _ack_articles(self, ids: list[int], headers: dict) -> None:
        url = f"{self.base_url}/api/articles/ack"
        try:
            resp = requests.post(
                url,
                json={"ids": ids},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            logger.info("RU Collector: acknowledged %d articles", len(ids))
        except requests.RequestException as exc:
            logger.error("Failed to ack articles on RU Collector: %s", exc)
