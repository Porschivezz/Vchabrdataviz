"""Habr.com scraper: HTML page scraping + kek/v2 API for full content.

Collects ALL publications within the date range by paginating through
Habr website article listing pages and enriching with kek/v2 API.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.core.config import settings

logger = logging.getLogger(__name__)

HABR_ARTICLES_LIST = "https://habr.com/ru/articles/"
HABR_API_BASE = "https://habr.com/kek/v2"

MAX_PAGES = 500


class HabrScraper(BaseScraper):
    """Fetches ALL articles from Habr within a date range.

    Uses website HTML pages for article listing (with pagination)
    and kek/v2 API for full article body enrichment.
    """

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://habr.com/",
        })
        proxy_url = settings.scraper_proxy_url.strip()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = self._ensure_tz(since)
        until_aware = self._ensure_tz(until) if until else datetime.now(timezone.utc)

        all_stubs: list[dict] = []
        seen_ids: set[str] = set()
        consecutive_old_pages = 0
        empty_pages = 0

        for page in range(1, MAX_PAGES + 1):
            stubs = self._fetch_html_page(page)

            if not stubs:
                empty_pages += 1
                if empty_pages >= 3:
                    logger.info("Habr: 3 consecutive empty pages, stopping at page %d", page)
                    break
                continue
            else:
                empty_pages = 0

            in_range = 0
            too_old = 0
            too_new = 0

            for stub in stubs:
                art_id = stub["id"]
                if art_id in seen_ids:
                    continue
                seen_ids.add(art_id)

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

            # Track consecutive all-old pages
            if too_old > 0 and in_range == 0 and too_new == 0:
                consecutive_old_pages += 1
            else:
                consecutive_old_pages = 0

            if consecutive_old_pages >= 3:
                logger.info(
                    "Habr: 3 consecutive all-old pages, stopping at page %d", page,
                )
                break

            if page % 10 == 0:
                logger.info(
                    "Habr page %d: collected %d stubs so far "
                    "(this page: %d in range, %d old, %d new)",
                    page, len(all_stubs), in_range, too_old, too_new,
                )

            # Be polite
            if page % 5 == 0:
                time.sleep(0.5)

        total_pages = min(page, MAX_PAGES)
        logger.info(
            "Habr: collected %d stubs in range %s – %s (pages scanned: %d)",
            len(all_stubs), since_aware.date(), until_aware.date(), total_pages,
        )

        # Enrich stubs with full body via API
        articles: list[RawArticle] = []
        for i, stub in enumerate(all_stubs):
            article = self._enrich_article(stub)
            if article is not None:
                articles.append(article)
            if (i + 1) % 100 == 0:
                logger.info("Habr: enriched %d / %d articles", i + 1, len(all_stubs))

        logger.info("Habr TOTAL: %d articles fetched", len(articles))
        return articles

    # ------------------------------------------------------------------

    def _fetch_html_page(self, page: int) -> list[dict]:
        """Fetch one page of the Habr articles listing via HTML scraping."""
        url = HABR_ARTICLES_LIST if page == 1 else f"{HABR_ARTICLES_LIST}page{page}/"

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 404:
                    return []
                if resp.status_code == 429:
                    wait = 2 ** attempt * 2
                    logger.warning("Habr rate limited (429), waiting %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                logger.error("Habr HTML page %d failed: %s", page, exc)
                return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items: list[dict] = []

        # Find article cards — Habr uses <article> tags with data-id attribute
        article_els = soup.select("article.tm-articles-list__item")
        if not article_els:
            # Fallback: try other selectors
            article_els = soup.select("article[id^='post-']")
        if not article_els:
            article_els = soup.select("article")

        for el in article_els:
            stub = self._parse_article_element(el)
            if stub:
                items.append(stub)

        if page == 1:
            logger.info("Habr HTML page 1: found %d article elements", len(items))

        return items

    def _parse_article_element(self, el) -> dict | None:
        """Parse a single <article> element into a stub dict."""
        # Extract article ID from data-id or link
        article_id = el.get("data-id") or el.get("id", "").replace("post-", "")

        # Find the title link
        title_el = (
            el.select_one("a.tm-title__link")
            or el.select_one("h2 a")
            or el.select_one("a.tm-article-snippet__title-link")
            or el.select_one("a[href*='/articles/']")
        )
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")

        # Build full link
        if href.startswith("/"):
            link = f"https://habr.com{href}"
        elif href.startswith("http"):
            link = href
        else:
            return None

        # Extract article ID from link if not found on element
        if not article_id:
            m = re.search(r"/articles/(\d+)", link)
            if m:
                article_id = m.group(1)
            else:
                return None

        link = self._normalize_link(link)

        # Extract datetime
        time_el = el.select_one("time") or el.select_one("span.tm-article-datetime-published time")
        pub_dt = None
        if time_el:
            dt_str = time_el.get("datetime", "")
            if dt_str:
                pub_dt = self._parse_iso(dt_str)
            if not pub_dt:
                title_attr = time_el.get("title", "")
                if title_attr:
                    pub_dt = self._parse_iso(title_attr)

        # Extract tags/hubs
        tags = []
        for hub_el in el.select("a.tm-publication-hub__link, a[href*='/hub/']"):
            tag_text = hub_el.get_text(strip=True)
            if tag_text:
                tags.append(tag_text)

        # Extract snippet/description
        snippet_el = el.select_one("div.tm-article-body, div.article-formatted-body, .tm-article-snippet__lead")
        description = snippet_el.get_text(separator="\n", strip=True) if snippet_el else ""

        return {
            "id": str(article_id),
            "title": title,
            "link": link,
            "published_at": pub_dt,
            "description": description,
            "tags": tags,
        }

    def _enrich_article(self, stub: dict) -> RawArticle | None:
        """Fetch full article body from kek/v2 API."""
        article_id = stub["id"]
        raw_text = stub.get("description", "")

        # If we have a good snippet, try to get full text from API
        try:
            resp = self.session.get(
                f"{HABR_API_BASE}/articles/{article_id}",
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                body_html = (
                    data.get("textHtml")
                    or data.get("article", {}).get("textHtml")
                    or ""
                )
                if body_html:
                    raw_text = self._html_to_text(body_html)
        except Exception as exc:
            logger.debug("Habr kek API failed for %s: %s", article_id, exc)

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
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _parse_iso(s: str) -> datetime | None:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
