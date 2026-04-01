"""Habr.com scraper: RSS pagination by date range + kek/v2 API for full content.

Collects ALL publications within the date range by paginating
through RSS pages until 3 consecutive pages are entirely older than ``since``.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)

HABR_RSS = "https://habr.com/ru/rss/all/all/"
HABR_API_BASE = "https://habr.com/kek/v2"

# Habr RSS: ~40 items/page. For a full day with ~500-1000 articles,
# need ~25-50 pages. Allow up to 500 pages for multi-day ranges.
MAX_PAGES = 500


class HabrScraper(BaseScraper):
    """Fetches ALL articles from Habr within a date range.

    Uses RSS for article listing (with pagination) and kek/v2 API
    for full article body enrichment.
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
        seen_links: set[str] = set()
        consecutive_old_pages = 0

        for page in range(1, MAX_PAGES + 1):
            stubs = self._fetch_rss_page(page)
            if not stubs:
                break

            in_range = 0
            too_old = 0
            too_new = 0

            for stub in stubs:
                link = stub["link"]
                if link in seen_links:
                    continue
                seen_links.add(link)

                pub = stub.get("published_at")
                if pub is None:
                    all_stubs.append(stub)
                    in_range += 1
                    continue

                pub_aware = self._ensure_tz(pub)

                if pub_aware > until_aware:
                    too_new += 1
                    continue
                if pub_aware < since_aware:
                    too_old += 1
                    continue

                all_stubs.append(stub)
                in_range += 1

            # Track consecutive all-old pages (require 3 to confirm boundary)
            if too_old > 0 and in_range == 0 and too_new == 0:
                consecutive_old_pages += 1
            else:
                consecutive_old_pages = 0

            if consecutive_old_pages >= 3:
                logger.info(
                    "Habr: 3 consecutive all-old pages, stopping at page %d", page,
                )
                break

            # Progress logging every 10 pages
            if page % 10 == 0:
                logger.info(
                    "Habr RSS page %d: collected %d stubs so far "
                    "(this page: %d in range, %d old, %d new)",
                    page, len(all_stubs), in_range, too_old, too_new,
                )

        logger.info(
            "Habr: collected %d stubs in range %s – %s (pages scanned: %d)",
            len(all_stubs), since_aware.date(), until_aware.date(), page,
        )

        # Enrich stubs with full body via API
        articles: list[RawArticle] = []
        for i, stub in enumerate(all_stubs):
            article = self._enrich_with_api(stub)
            if article is not None:
                articles.append(article)
            if (i + 1) % 100 == 0:
                logger.info("Habr: enriched %d / %d articles", i + 1, len(all_stubs))

        logger.info("Habr TOTAL: %d articles fetched", len(articles))
        return articles

    # ------------------------------------------------------------------

    def _fetch_rss_page(self, page: int) -> list[dict]:
        """Fetch one page of Habr RSS."""
        url = HABR_RSS if page == 1 else f"{HABR_RSS}page{page}/"

        for attempt in range(2):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 0:
                    time.sleep(1)
                    continue
                logger.error("Habr RSS page %d failed: %s", page, exc)
                return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("Habr RSS parse error (page %d): %s", page, exc)
            return []

        items: list[dict] = []
        for item_el in root.findall(".//item"):
            link = self._normalize_link((item_el.findtext("link") or "").strip())
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

    @staticmethod
    def _ensure_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _normalize_link(link: str) -> str:
        """Strip UTM and tracking query params."""
        parsed = urlparse(link)
        kept = {
            k: v for k, v in parse_qs(parsed.query).items()
            if not k.startswith("utm_") and k not in ("campaign",)
        }
        clean_query = urlencode(kept, doseq=True)
        return urlunparse(parsed._replace(query=clean_query))

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
