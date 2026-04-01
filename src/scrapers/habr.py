"""Habr.com scraper: RSS pagination by date range + kek/v2 API for full content."""

from __future__ import annotations

import logging
import re
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

MAX_PAGES = 200  # safety limit


class HabrScraper(BaseScraper):
    """Fetches articles from Habr via RSS (for list) + kek/v2 API (for full body).

    Paginates RSS pages backwards until the majority of articles on a page
    are older than ``since``, then stops.
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
        stop_paging = False

        for page in range(1, MAX_PAGES + 1):
            stubs = self._fetch_rss_page(page)
            if not stubs:
                break

            in_range = 0
            too_old = 0

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
                    continue  # too new, skip
                if pub_aware < since_aware:
                    too_old += 1
                    continue  # too old, skip but count

                all_stubs.append(stub)
                in_range += 1

            # Stop when the entire page is older than our range
            total_on_page = in_range + too_old
            if total_on_page > 0 and too_old == total_on_page:
                stop_paging = True

            if page % 10 == 0:
                logger.info(
                    "Habr RSS page %d: %d in range, %d too old, total collected: %d",
                    page, in_range, too_old, len(all_stubs),
                )

            if stop_paging:
                break

        logger.info(
            "Habr: collected %d stubs in range %s – %s (pages scanned: %d)",
            len(all_stubs), since_aware.date(), until_aware.date(), page,
        )

        # Enrich each stub with full body
        articles: list[RawArticle] = []
        for i, stub in enumerate(all_stubs):
            article = self._enrich_with_api(stub)
            if article is not None:
                articles.append(article)
            if (i + 1) % 100 == 0:
                logger.info("Habr: enriched %d / %d articles", i + 1, len(all_stubs))

        logger.info("Habr: fetched %d articles total", len(articles))
        return articles

    # ------------------------------------------------------------------

    def _fetch_rss_page(self, page: int) -> list[dict]:
        """Fetch one page of Habr RSS."""
        url = HABR_RSS if page == 1 else f"{HABR_RSS}page{page}/"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                return []
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
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _normalize_link(link: str) -> str:
        """Strip UTM and tracking query params, keep canonical URL."""
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
