"""ТАСС news source parser."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import httpx
import feedparser
from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser
from dateutil import parser as dateparser
from aiolimiter import AsyncLimiter
from tenacity import retry, stop_after_attempt, wait_exponential

from hm_api.services.ingestion.base import BaseSource, DiscoveredUrl, ParsedArticle
from hm_api.core.metrics import (
    http_client_request_duration_seconds,
    http_client_requests_total,
    ingest_errors_total,
)
from hm_api.services.ingestion.utils import normalize_url


TASS_HOME = "https://tass.ru"


class TassSource(BaseSource):
    """Parser for TASS (ТАСС) news agency."""

    slug = "tass"
    name = "ТАСС"
    homepage_url = TASS_HOME
    poll_interval = timedelta(minutes=20)

    # RSS feeds by section
    RSS_FEEDS = [
        f"{TASS_HOME}/rss/v2.xml",  # Main feed
        # Section-specific feeds
        f"{TASS_HOME}/rss/v2.xml?sections=MEhvM9YoKE4",  # Политика
        f"{TASS_HOME}/rss/v2.xml?sections=T1BvM9YCjLk",  # Экономика
        f"{TASS_HOME}/rss/v2.xml?sections=SurvM9YC7RI",  # Общество
        f"{TASS_HOME}/rss/v2.xml?sections=QE5vM9YCE3M",  # Мир
        f"{TASS_HOME}/rss/v2.xml?sections=vDFvM9Ycjuk",  # Наука
    ]

    # Sitemap for archive
    SITEMAP_INDEX = f"{TASS_HOME}/sitemap-index.xml"

    # Sections to include
    ALLOWED_SECTIONS = {
        "politika",
        "ekonomika",
        "obschestvo",
        "v-strane",
        "mezhdunarodnaya-panorama",
        "nauka",
        "kultura",
        "sport",
        "armiya-i-opk",
        "nacionalnye-proekty",
        "moskva",
        "opinions",
    }

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
        self.client = client or httpx.AsyncClient(
            headers={
                "User-Agent": "HMMonitoringBot/1.0 (+https://huginnmuninn.tech/bot-info)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        # Rate limit: 3 requests/second to be respectful
        self.limiter = AsyncLimiter(max_rate=3, time_period=1)

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=5))
    async def _fetch_text(self, url: str) -> str:
        """Fetch URL content with rate limiting and retries."""
        method = "GET"
        try:
            async with self.limiter:
                with http_client_request_duration_seconds.labels(self.slug, method).time():
                    resp = await self.client.get(url)
            http_client_requests_total.labels(self.slug, method, str(resp.status_code)).inc()
            resp.raise_for_status()
            return resp.text
        except Exception:
            ingest_errors_total.labels(self.slug, "fetch").inc()
            raise

    def _is_article_url(self, href: str) -> bool:
        """Check if URL is an article page."""
        if not href.startswith(TASS_HOME):
            return False

        path = href[len(TASS_HOME):]

        # Exclude non-article pages
        excluded = (
            "/info/",
            "/tag/",
            "/author/",
            "/search",
            "/spec/",
            "/press/",
            "/podcasts/",
            "/video/",
            "/photo/",
            "/rss",
        )
        if any(path.startswith(s) for s in excluded):
            return False

        # Match article URL pattern: /section/number or /section/sub/number
        # Examples:
        # /ekonomika/22760897
        # /mezhdunarodnaya-panorama/22760541
        pattern = r"^/[\w-]+(/[\w-]+)?/\d+$"
        return bool(re.match(pattern, path))

    async def _iter_rss(self) -> AsyncIterator[DiscoveredUrl]:
        """Iterate over RSS feeds to discover articles."""

        async def fetch_feed(feed_url: str) -> list[DiscoveredUrl]:
            try:
                text = await self._fetch_text(feed_url)
            except Exception:
                return []

            parsed = feedparser.parse(text)
            items: list[DiscoveredUrl] = []

            for entry in parsed.entries:
                href = normalize_url(getattr(entry, "link", ""))
                if not href or not self._is_article_url(href):
                    continue

                published = None
                for field in ("published", "updated", "pubDate"):
                    val = getattr(entry, field, None)
                    if val:
                        try:
                            published = dateparser.parse(val)
                            break
                        except Exception:
                            continue

                items.append(DiscoveredUrl(url=href, published_at=published))

            return items

        # Fetch all feeds concurrently
        tasks = [fetch_feed(url) for url in self.RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen: set[str] = set()
        for batch in results:
            if isinstance(batch, Exception):
                continue
            for item in batch:
                if item.url not in seen:
                    seen.add(item.url)
                    yield item

    async def _iter_sitemap(self, cutoff: datetime | None = None) -> AsyncIterator[DiscoveredUrl]:
        """Iterate over sitemap for article discovery."""

        async def fetch_soup(url: str) -> BeautifulSoup | None:
            try:
                xml = await self._fetch_text(url)
                return BeautifulSoup(xml, "xml")
            except Exception:
                return None

        # Get sitemap index
        root = await fetch_soup(self.SITEMAP_INDEX)
        if not root:
            return

        # Find child sitemaps
        sitemaps = [loc.text.strip() for loc in root.select("sitemap > loc") if loc.text]

        # Process only recent sitemaps (by lastmod date)
        for sitemap_url in sitemaps[:10]:  # Limit to most recent
            soup = await fetch_soup(sitemap_url)
            if not soup:
                continue

            for url_tag in soup.select("url"):
                loc = url_tag.select_one("loc")
                lastmod = url_tag.select_one("lastmod")

                if not loc or not loc.text:
                    continue

                href = normalize_url(loc.text.strip())
                if not self._is_article_url(href):
                    continue

                published = None
                if lastmod and lastmod.text:
                    try:
                        published = dateparser.parse(lastmod.text.strip())
                    except Exception:
                        pass

                # Skip if before cutoff
                if cutoff and published and published < cutoff:
                    continue

                yield DiscoveredUrl(url=href, published_at=published)

    async def discover_all(self) -> AsyncIterator[DiscoveredUrl]:
        """Discover all articles via sitemap."""
        async for item in self._iter_sitemap():
            yield item

    async def discover_recent(self) -> AsyncIterator[DiscoveredUrl]:
        """Discover recent articles via RSS and recent sitemap."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        seen: set[str] = set()

        # RSS first (most recent)
        async for item in self._iter_rss():
            if item.url not in seen:
                seen.add(item.url)
                yield item

        # Augment with sitemap (catches any missed)
        async for item in self._iter_sitemap(cutoff=cutoff):
            if item.url not in seen:
                seen.add(item.url)
                yield item

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """
        Parse datetime as-is (без принудительной смены часового пояса).
        Возвращает то, что указано на странице (как работало ранее).
        """
        if not value:
            return None
        try:
            return dateparser.parse(value)
        except Exception:
            return None

    async def parse_article(self, url: str) -> ParsedArticle:
        """Parse a single TASS article page."""
        html = await self._fetch_text(url)
        tree = HTMLParser(html)

        # Title - multiple possible selectors
        title = None
        for sel in (
            "h1.news-header__title",
            "h1.NewsHeader_title",
            "h1[class*='title']",
            "h1",
        ):
            node = tree.css_first(sel)
            if node and node.text(strip=True):
                title = node.text(strip=True)
                break

        if not title:
            # Fallback to og:title
            og_title = tree.css_first('meta[property="og:title"]')
            if og_title and og_title.attributes.get("content"):
                title = og_title.attributes["content"].strip()

        title = title or ""

        # Subtitle/lead
        subtitle = None
        for sel in (
            "div.news-header__lead",
            "div.NewsHeader_lead",
            "p.lead",
            "div[class*='lead']",
        ):
            node = tree.css_first(sel)
            if node and node.text(strip=True):
                subtitle = node.text(strip=True)
                break

        # Content - article body
        content_nodes = (
            tree.css("div.text-content p")
            or tree.css("div.news-body p")
            or tree.css("div.NewsBody p")
            or tree.css("article p")
            or tree.css("div[class*='text'] p")
        )

        paragraphs: list[str] = []
        for node in content_nodes:
            # Skip captions, ads, promo
            parent_class = node.parent.attributes.get("class", "") if node.parent else ""
            if any(x in parent_class.lower() for x in ("caption", "promo", "advert", "related")):
                continue
            text = node.text(strip=True)
            if text and len(text) > 20:  # Filter out very short paragraphs
                paragraphs.append(text)

        body_text = "\n\n".join(paragraphs)

        # Authors
        authors: list[str] | None = None
        author_nodes = tree.css("a[href*='/author/'], span[class*='author']")
        if author_nodes:
            authors = [n.text(strip=True) for n in author_nodes if n.text(strip=True)] or None

        # Section
        section = None
        # Try breadcrumbs first
        breadcrumb = tree.css_first("nav.breadcrumbs a:last-child, a[class*='breadcrumb']")
        if breadcrumb:
            section = breadcrumb.text(strip=True)
        # Fallback: extract from URL
        if not section:
            match = re.search(r"tass\.ru/([^/]+)/", url)
            if match:
                section = match.group(1).replace("-", " ").title()

        # Tags
        tags: list[str] | None = None
        tag_nodes = tree.css("a[href*='/tag/'], div.tags a")
        if tag_nodes:
            tags = [n.text(strip=True) for n in tag_nodes if n.text(strip=True)] or None

        # Published date - try multiple methods, без принудительной смены TZ
        published_at: datetime | None = None

        # Method 1: time element with datetime attribute
        time_node = tree.css_first("time[datetime]")
        if time_node and time_node.attributes.get("datetime"):
            published_at = self._parse_datetime(time_node.attributes["datetime"])

        # Method 2: TASS-specific date selectors (including the visible time span)
        if not published_at:
            date_selectors = [
                "span.news-header__date",
                "div.news-header__date",
                "span.NewsHeader_date",
                "div.NewsHeader_date",
                "span[class*='Date_text']",
                "span[class*='date']",
                "div[class*='date']",
                "span.date",
                "div.date",
            ]
            for sel in date_selectors:
                node = tree.css_first(sel)
                if node and node.text(strip=True):
                    date_text = node.text(strip=True)
                    published_at = self._parse_datetime(date_text)
                    if published_at:
                        break

        # Method 3: article:published_time meta tag
        if not published_at:
            meta_pt = tree.css_first('meta[property="article:published_time"]')
            if meta_pt and meta_pt.attributes.get("content"):
                published_at = self._parse_datetime(meta_pt.attributes["content"])

        # Method 4: og:updated_time meta tag
        if not published_at:
            meta_ut = tree.css_first('meta[property="og:updated_time"]')
            if meta_ut and meta_ut.attributes.get("content"):
                published_at = self._parse_datetime(meta_ut.attributes["content"])

        # Method 5: datePublished / dateCreated / dateModified in JSON-LD
        if not published_at:
            for script in tree.css('script[type="application/ld+json"]'):
                try:
                    import json
                    data = json.loads(script.text())
                    if isinstance(data, dict):
                        for key in ("datePublished", "dateCreated", "dateModified"):
                            if key in data:
                                published_at = self._parse_datetime(data[key])
                                break
                    if published_at:
                        break
                except Exception:
                    continue

        # If still none, leave as None (handled downstream)

        # Canonical URL
        canonical_url = None
        link_canon = tree.css_first("link[rel='canonical']")
        if link_canon and link_canon.attributes.get("href"):
            canonical_url = normalize_url(link_canon.attributes["href"])

        return ParsedArticle(
            url=normalize_url(url),
            canonical_url=canonical_url,
            title=title,
            subtitle=subtitle,
            body_text=body_text,
            body_html=None,
            authors=authors,
            section=section,
            tags=tags,
            published_at=published_at,
        )


SOURCE_CLS = TassSource

__all__ = ["TassSource", "SOURCE_CLS"]

