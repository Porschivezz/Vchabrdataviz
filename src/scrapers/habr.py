"""Habr.com scraper: RSS pagination by date range + kek/v2 API for full content."""

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

MAX_PAGES = 50  # safety limit to avoid infinite pagination


class HabrScraper(BaseScraper):
    """Fetches articles from Habr via RSS (for list) + kek/v2 API (for full body).

    Paginates RSS pages backwards until all articles in the date range are collected.
    """

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

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = self._ensure_tz(since)
        until_aware = self._ensure_tz(until) if until else datetime.now(timezone.utc)

        all_stubs: list[dict] = []
        reached_boundary = False

        for page in range(1, MAX_PAGES + 1):
            stubs = self._fetch_rss_page(page)
            if not stubs:
                break

            for stub in stubs:
                pub = stub.get("published_at")
                if pub is None:
                    # No date — include it (we'll filter later if needed)
                    all_stubs.append(stub)
                    continue

                pub_aware = self._ensure_tz(pub)

                if pub_aware > until_aware:
                    # Too new, skip but keep paginating
                    continue
                if pub_aware < since_aware:
                    # Older than range — we've gone past the boundary
                    reached_boundary = True
                    break

                all_stubs.append(stub)

            if reached_boundary:
                break

        logger.info(
            "Habr: collected %d stubs in range %s – %s (pages: %d)",
            len(all_stubs), since_aware.date(), until_aware.date(), page,
        )

        # Enrich each stub with full body
        articles: list[RawArticle] = []
        for stub in all_stubs:
            article = self._enrich_with_api(stub)
            if article is not None:
                articles.append(article)

        logger.info("Habr: fetched %d articles", len(articles))
        return articles

    # ------------------------------------------------------------------

    def _fetch_rss_page(self, page: int) -> list[dict]:
        """Fetch one page of Habr RSS."""
        url = HABR_RSS if page == 1 else f"{HABR_RSS}page{page}/"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                return []  # no more pages
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Habr RSS page %d failed: %s", page, exc)
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("Habr RSS parse error (page %d): %s", page, exc)
            return []

        items: list[dict] = []
        for item_el in root.findall(".//item"):
            link = (item_el.findtext("link") or "").strip()
            title = (item_el.findtext("title") or "").strip()
            pub_str = (item_el.findtext("pubDate") or "").strip()
            description = (item_el.findtext("description") or "").strip()

            article_id = self._extract_id(link)
            if not article_id:
                continue

            tags = [
                c.text.strip()
                for c in item_el.findall("category")
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

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
