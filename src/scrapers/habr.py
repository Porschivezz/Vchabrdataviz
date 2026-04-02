"""Habr.com scraper: kek/v2 API for article listing + full content.

Collects ALL publications within the date range by paginating
through the Habr articles API until 3 consecutive pages are entirely
older than ``since``.
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

logger = logging.getLogger(__name__)

HABR_API_BASE = "https://habr.com/kek/v2"
HABR_ARTICLES_URL = f"{HABR_API_BASE}/articles/"

# Habr publishes ~500-1500 articles/day. At 20 items/page that's up to 75 pages.
# Allow up to 500 pages for multi-day ranges.
MAX_PAGES = 500
PER_PAGE = 20


class HabrScraper(BaseScraper):
    """Fetches ALL articles from Habr within a date range.

    Uses kek/v2 API for both article listing and full body enrichment.
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
        seen_ids: set[str] = set()
        consecutive_old_pages = 0

        for page in range(1, MAX_PAGES + 1):
            stubs = self._fetch_api_page(page)
            if not stubs:
                logger.info("Habr API page %d: empty response, stopping", page)
                break

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

            # Progress logging every 10 pages
            if page % 10 == 0:
                logger.info(
                    "Habr API page %d: collected %d stubs so far "
                    "(this page: %d in range, %d old, %d new)",
                    page, len(all_stubs), in_range, too_old, too_new,
                )

            # Small delay to be polite
            if page % 5 == 0:
                time.sleep(0.3)

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

    def _fetch_api_page(self, page: int) -> list[dict]:
        """Fetch one page of articles from Habr kek/v2 API."""
        params = {
            "page": page,
            "perPage": PER_PAGE,
            "sort": "date",
            "fl": "ru",
            "hl": "ru",
        }

        for attempt in range(3):
            try:
                resp = self.session.get(
                    HABR_ARTICLES_URL,
                    params=params,
                    timeout=self.timeout,
                )
                if resp.status_code == 404:
                    return []
                if resp.status_code == 429:
                    # Rate limited — wait and retry
                    wait = min(2 ** attempt * 2, 30)
                    logger.warning("Habr API rate limited (429), waiting %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                logger.error("Habr API page %d failed: %s", page, exc)
                return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("Habr API page %d JSON parse error: %s", page, exc)
            return []

        return self._parse_api_response(data, page)

    def _parse_api_response(self, data: dict, page: int) -> list[dict]:
        """Parse the kek/v2/articles response into stub dicts.

        The response format can be:
        1. {"articleIds": [...], "articleRefs": {id: {...}}}
        2. {"articles": [...]}  (list of article objects)
        3. {"publicationIds": [...], "publicationRefs": {id: {...}}}
        """
        items = []

        # Format 1: articleIds + articleRefs
        article_ids = data.get("articleIds") or data.get("publicationIds") or []
        article_refs = data.get("articleRefs") or data.get("publicationRefs") or {}

        if article_ids and article_refs:
            for aid in article_ids:
                art = article_refs.get(str(aid))
                if not art:
                    continue
                items.append(self._article_ref_to_stub(art, str(aid)))
            if items:
                return items

        # Format 2: articles list
        articles_list = data.get("articles") or []
        if isinstance(articles_list, list):
            for art in articles_list:
                if isinstance(art, dict):
                    aid = str(art.get("id", ""))
                    if aid:
                        items.append(self._article_ref_to_stub(art, aid))
            if items:
                return items

        # Format 3: try to find any list of dicts at top level
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                for art in value:
                    aid = str(art.get("id", ""))
                    if aid:
                        items.append(self._article_ref_to_stub(art, aid))
                if items:
                    return items

        # Log unknown format for debugging
        if page == 1:
            keys = list(data.keys())[:10]
            logger.warning(
                "Habr API page %d: unknown response format. Top keys: %s",
                page, keys,
            )

        return items

    def _article_ref_to_stub(self, art: dict, article_id: str) -> dict:
        """Convert an article ref object to a stub dict."""
        # Title
        title = art.get("titleHtml") or art.get("title") or ""
        if "<" in title:
            title = BeautifulSoup(title, "html.parser").get_text(strip=True)

        # Link
        slug = art.get("slug") or art.get("alias") or ""
        if slug:
            link = f"https://habr.com/ru/articles/{article_id}/"
        else:
            link = f"https://habr.com/ru/articles/{article_id}/"

        # Published date
        pub_dt = None
        time_published = art.get("timePublished") or art.get("publishedAt") or ""
        if time_published:
            pub_dt = self._parse_iso(time_published)

        # Tags / hubs
        tags = []
        hubs = art.get("hubs") or []
        if isinstance(hubs, list):
            for h in hubs:
                if isinstance(h, dict):
                    tags.append(h.get("title") or h.get("alias") or "")
                elif isinstance(h, str):
                    tags.append(h)
        flow = art.get("flows") or []
        if isinstance(flow, list):
            for f in flow:
                if isinstance(f, dict):
                    tags.append(f.get("title") or f.get("alias") or "")

        tags = [t.strip() for t in tags if t.strip()]

        # Body text (may be available inline)
        body_html = art.get("textHtml") or art.get("leadData", {}).get("textHtml", "") or ""
        description = self._html_to_text(body_html) if body_html else ""

        return {
            "id": article_id,
            "title": title,
            "link": self._normalize_link(link),
            "published_at": pub_dt,
            "description": description,
            "tags": tags,
            "has_full_text": bool(art.get("textHtml")),
        }

    def _enrich_article(self, stub: dict) -> RawArticle | None:
        """Fetch full article body from kek/v2 API if not already available."""
        article_id = stub["id"]
        raw_text = stub.get("description", "")

        # If we already have full text from listing, skip enrichment
        if stub.get("has_full_text") and raw_text and len(raw_text) > 200:
            return RawArticle(
                source="habr",
                title=stub["title"],
                link=stub["link"],
                published_at=stub["published_at"],
                raw_text=raw_text,
                native_tags=stub["tags"],
            )

        # Fetch full body from API
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
