"""Universal RSS/Atom feed scraper for Russian news sources.

Uses requests + BeautifulSoup for XML parsing (no feedparser needed).
Supports multiple feed URLs per source, date filtering, and
full-page article text extraction via CSS selectors.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.core.config import settings

logger = logging.getLogger(__name__)


def _get_proxy_dict() -> dict | None:
    """Build requests-compatible proxy dict from settings."""
    url = settings.scraper_proxy_url.strip()
    if not url:
        return None
    return {"http": url, "https": url}


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
        proxies = _get_proxy_dict()
        if proxies:
            self.session.proxies.update(proxies)
            logger.debug("%s: using proxy %s", source_name, settings.scraper_proxy_url[:30])

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
        resp = None

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

        if resp is None:
            return []

        # Parse XML with BeautifulSoup
        soup = BeautifulSoup(resp.content, "xml")
        if not soup:
            # Fallback to html.parser for malformed XML
            soup = BeautifulSoup(resp.content, "html.parser")

        # Try RSS <item> elements first, then Atom <entry>
        items = soup.find_all("item")
        is_atom = False
        if not items:
            items = soup.find_all("entry")
            is_atom = True

        if not items:
            logger.warning("%s RSS: no items found in %s", self.source_name, feed_url)
            return []

        for item in items:
            link = self._extract_link(item, is_atom)
            if not link or link in seen_links:
                continue

            pub_dt = self._extract_item_date(item)
            if pub_dt is not None:
                pub_aware = _ensure_tz(pub_dt)
                if pub_aware > until or pub_aware < since:
                    continue

            seen_links.add(link)

            title = ""
            title_el = item.find("title")
            if title_el:
                title = title_el.get_text(strip=True)

            # Extract text from RSS content
            raw_text = self._extract_item_text(item, is_atom)

            # Fetch full page text if configured and RSS text is short
            if self.fetch_full_page and self.full_text_selector:
                full_text = self._fetch_full_text(link)
                if full_text and len(full_text) > len(raw_text):
                    raw_text = full_text

            tags = self._extract_tags(item)

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

    def _extract_link(self, item, is_atom: bool) -> str:
        if is_atom:
            link_el = item.find("link")
            if link_el:
                href = link_el.get("href", "")
                if href:
                    return href.strip()
                return link_el.get_text(strip=True)
        else:
            link_el = item.find("link")
            if link_el:
                text = link_el.get_text(strip=True)
                if text:
                    return text
                href = link_el.get("href", "")
                if href:
                    return href.strip()
            # Fallback: guid
            guid_el = item.find("guid")
            if guid_el:
                guid = guid_el.get_text(strip=True)
                if guid.startswith("http"):
                    return guid
        return ""

    def _extract_item_date(self, item) -> datetime | None:
        for tag_name in ("pubDate", "published", "updated", "dc:date", "date"):
            el = item.find(tag_name)
            if el:
                text = el.get_text(strip=True)
                if text:
                    dt = _parse_datetime(text)
                    if dt:
                        return dt
        return None

    def _extract_item_text(self, item, is_atom: bool) -> str:
        # Try multiple content fields
        for tag_name in ("content:encoded", "content", "description", "summary"):
            el = item.find(tag_name)
            if el:
                text = el.get_text(strip=True) if el.string is None else el.string.strip()
                if text:
                    # Check if it's HTML
                    if "<" in text and ">" in text:
                        return _html_to_text(text)
                    return text

        # For Atom feeds, check <content type="html">
        if is_atom:
            content_el = item.find("content")
            if content_el and content_el.get("type") == "html":
                return _html_to_text(content_el.get_text())

        return ""

    def _extract_tags(self, item) -> list[str]:
        tags = []
        for cat in item.find_all("category"):
            term = cat.get("term", "") or cat.get_text(strip=True)
            if term:
                tags.append(term)
        return tags

    def _fetch_full_text(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove noise elements
            for tag in soup.select("script, style, nav, header, footer, aside, iframe, noscript"):
                tag.decompose()

            # 1) Try each source-specific selector
            if self.full_text_selector:
                for selector in self.full_text_selector.split(","):
                    selector = selector.strip()
                    el = soup.select_one(selector)
                    if el:
                        text = el.get_text(separator="\n", strip=True)
                        if text and len(text) > 100:
                            return text

            # 2) Try common article selectors
            for fallback_sel in (
                "[itemprop='articleBody']",
                "article .text-content",
                "article .article-text",
                "div.article-body",
                "div.article__body",
                "div.article__text",
                "div.article_text",
                "div.article-content",
                "div.news-text",
                "div.text-block",
                "div.b-text",
                "div.post-content",
                "div.entry-content",
                "div.story__text",
                "div.js-mediator-article",
                "div.styled-text",
                "div.content-text",
                "div.topic-body__content",
                "div.maintext",
                "article",
                "main article",
            ):
                el = soup.select_one(fallback_sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if text and len(text) > 200:
                        return text

            # 3) Smart fallback: find the largest text-dense block
            text = _extract_largest_text_block(soup)
            if text and len(text) > 300:
                return text

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


def _extract_largest_text_block(soup: BeautifulSoup) -> str:
    """Find the DOM element with the highest density of <p> text content.

    Walks all divs/articles/sections, scores each by total paragraph
    text length, and returns the best one. This works regardless of
    CSS class names — catches any article body container.
    """
    best_text = ""
    best_score = 0

    for container in soup.find_all(["div", "article", "section", "main"]):
        paragraphs = container.find_all("p", recursive=True)
        if len(paragraphs) < 2:
            continue

        # Score = total text in <p> tags (penalize containers with too many links)
        p_text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        link_text = sum(len(a.get_text()) for a in container.find_all("a", recursive=True))
        text_len = len(p_text)

        # Penalize navigation-heavy blocks (>50% links)
        if text_len > 0 and link_text / text_len > 0.5:
            continue

        # Prefer deeper (more specific) containers with enough text
        if text_len > best_score and text_len > 200:
            best_score = text_len
            best_text = p_text

    return best_text


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _parse_datetime(text: str) -> datetime | None:
    """Parse various date formats found in RSS feeds."""
    if not text:
        return None

    # RFC 2822 (standard RSS)
    try:
        return parsedate_to_datetime(text)
    except Exception:
        pass

    # ISO 8601 (Atom, some RSS)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass

    # Common Russian date patterns
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None
