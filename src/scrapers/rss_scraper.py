"""Universal RSS/Atom feed scraper for Russian news sources.

Works with any site that provides a standard RSS or Atom feed.
Supports multiple feed URLs per source, date filtering, and
HTML content extraction.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)


class RssScraper(BaseScraper):
    """Generic RSS/Atom feed scraper.

    Parameters
    ----------
    source_name : str
        Identifier stored in ``RawArticle.source`` (e.g. "tass", "rbc").
    feed_urls : list[str]
        One or more RSS/Atom feed URLs to poll.
    fetch_full_page : bool
        If True, follow article links and scrape full text from the page.
    full_text_selector : str | None
        CSS selector for the article body on the full page.
    timeout : int
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        source_name: str,
        feed_urls: list[str],
        *,
        fetch_full_page: bool = False,
        full_text_selector: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.source_name = source_name
        self.feed_urls = feed_urls
        self.fetch_full_page = fetch_full_page
        self.full_text_selector = full_text_selector
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    # ------------------------------------------------------------------

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = _ensure_tz(since)
        until_aware = _ensure_tz(until) if until else datetime.now(timezone.utc)

        articles: list[RawArticle] = []
        seen_links: set[str] = set()

        for feed_url in self.feed_urls:
            feed_articles = self._parse_feed(
                feed_url, since_aware, until_aware, seen_links,
            )
            articles.extend(feed_articles)

        logger.info(
            "%s RSS: %d articles in range %s – %s",
            self.source_name, len(articles),
            since_aware.date(), until_aware.date(),
        )
        return articles

    # ------------------------------------------------------------------

    def _parse_feed(
        self,
        feed_url: str,
        since: datetime,
        until: datetime,
        seen_links: set[str],
    ) -> list[RawArticle]:
        articles: list[RawArticle] = []

        for attempt in range(3):
            try:
                resp = self.session.get(feed_url, timeout=self.timeout)
                if resp.status_code == 429:
                    wait = 2 ** attempt * 2
                    logger.warning("%s RSS rate limited, waiting %ds", self.source_name, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                logger.error("%s RSS feed %s failed: %s", self.source_name, feed_url, exc)
                return []

        feed = feedparser.parse(resp.content)

        if feed.bozo and not feed.entries:
            logger.warning(
                "%s RSS: feed parse error for %s: %s",
                self.source_name, feed_url, feed.bozo_exception,
            )
            return []

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            if not link or link in seen_links:
                continue

            pub_dt = self._extract_entry_date(entry)
            if pub_dt is not None:
                pub_aware = _ensure_tz(pub_dt)
                if pub_aware > until or pub_aware < since:
                    continue

            seen_links.add(link)

            title = entry.get("title", "").strip()
            raw_text = self._extract_entry_text(entry)

            # Optionally fetch full page content
            if self.fetch_full_page and self.full_text_selector:
                full_text = self._fetch_full_text(link)
                if full_text:
                    raw_text = full_text

            tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

            if not title and not raw_text:
                continue

            articles.append(RawArticle(
                source=self.source_name,
                title=title or "(без заголовка)",
                link=link,
                published_at=pub_dt,
                raw_text=raw_text,
                native_tags=tags,
            ))

        return articles

    # ------------------------------------------------------------------

    def _extract_entry_date(self, entry) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            tp = entry.get(field)
            if tp:
                try:
                    return datetime(*tp[:6], tzinfo=timezone.utc)
                except Exception:
                    pass

        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return parsedate_to_datetime(val)
                except Exception:
                    pass
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass

        return None

    def _extract_entry_text(self, entry) -> str:
        # Try content first (Atom), then summary (RSS)
        content_list = entry.get("content", [])
        if content_list:
            html = content_list[0].get("value", "")
            if html:
                return _html_to_text(html)

        summary = entry.get("summary", "")
        if summary:
            return _html_to_text(summary) if "<" in summary else summary

        description = entry.get("description", "")
        if description:
            return _html_to_text(description) if "<" in description else description

        return ""

    def _fetch_full_text(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            el = soup.select_one(self.full_text_selector)
            if el:
                return el.get_text(separator="\n", strip=True)
        except Exception as exc:
            logger.debug("%s: failed to fetch full text from %s: %s", self.source_name, url, exc)
        return ""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)
