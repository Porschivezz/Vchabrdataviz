"""Habr.com scraper: RSS for article list + kek/v2 API for full content."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)

HABR_RSS = "https://habr.com/ru/rss/all/all/"
HABR_API_BASE = "https://habr.com/kek/v2"


class HabrScraper(BaseScraper):
    """Fetches articles from Habr via RSS (for list) + kek/v2 API (for full body)."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://habr.com/",
            "Origin": "https://habr.com",
        })

    def fetch_articles(self, *, limit: int = 20) -> list[RawArticle]:
        rss_items = self._fetch_rss(limit=limit)
        articles: list[RawArticle] = []

        for item in rss_items:
            article = self._enrich_with_api(item)
            if article is not None:
                articles.append(article)

        logger.info("Habr: fetched %d articles", len(articles))
        return articles

    def _fetch_rss(self, limit: int) -> list[dict]:
        """Fetch article stubs from Habr RSS feed."""
        try:
            resp = self.session.get(HABR_RSS, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Habr RSS request failed: %s", exc)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("Habr RSS parse error: %s", exc)
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for item in root.findall(".//item")[:limit]:
            link = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or "").strip()
            pub_str = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()

            # Extract article ID from URL
            article_id = self._extract_id(link)
            if not article_id:
                continue

            # Parse categories/hubs as tags
            tags = [
                c.text.strip()
                for c in item.findall("category")
                if c.text and c.text.strip()
            ]

            pub_dt = self._parse_rfc2822(pub_str)

            items.append({
                "id": article_id,
                "title": title,
                "link": link,
                "published_at": pub_dt,
                "description": description,
                "tags": tags,
            })

        return items

    def _enrich_with_api(self, stub: dict) -> RawArticle | None:
        """Fetch full article body from kek/v2 API."""
        article_id = stub["id"]
        raw_text = ""

        try:
            resp = self.session.get(
                f"{HABR_API_BASE}/articles/{article_id}",
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                body_html = (
                    data.get("textHtml")
                    or data.get("article", {}).get("textHtml")
                    or ""
                )
                raw_text = self._html_to_text(body_html)
        except Exception as exc:
            logger.debug("Habr kek API failed for %s: %s", article_id, exc)

        # Fall back to RSS description if API gave nothing
        if not raw_text:
            raw_text = self._html_to_text(stub.get("description", ""))

        if not raw_text and not stub["title"]:
            return None

        return RawArticle(
            source="habr",
            title=stub["title"],
            link=stub["link"],
            published_at=stub["published_at"],
            raw_text=raw_text,
            native_tags=stub["tags"],
        )

    @staticmethod
    def _extract_id(link: str) -> str | None:
        m = re.search(r"/articles/(\d+)", link)
        return m.group(1) if m else None

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _parse_rfc2822(s: str) -> datetime | None:
        if not s:
            return None
        try:
            return parsedate_to_datetime(s)
        except Exception:
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None
