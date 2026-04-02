"""HTML-based scrapers for Russian news sites with broken/missing RSS.

Izvestia (iz.ru), Gazeta.ru, Экспресс газета (eg.ru).
These sites either removed their RSS feeds or block RSS access.
We scrape listing pages directly and fetch full article text.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.scrapers.rss_scraper import _ensure_tz, _parse_datetime, _extract_largest_text_block
from src.core.config import settings

logger = logging.getLogger(__name__)


class _BaseNewsHtmlScraper(BaseScraper):
    """Base HTML scraper for news listing pages."""

    source_name: str = ""
    base_url: str = ""
    listing_urls: list[str] = []
    link_pattern: str = ""  # Regex to match article URLs
    article_selectors: list[str] = []

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
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
        since_aware = _ensure_tz(since)
        until_aware = _ensure_tz(until) if until else datetime.now(timezone.utc)

        # Step 1: Collect article links from listing pages
        stubs = self._fetch_listings()
        logger.info("%s: %d article links found", self.source_name, len(stubs))

        # Step 2: Fetch each article, extract full text + date
        articles: list[RawArticle] = []
        for i, stub in enumerate(stubs):
            article = self._fetch_article(stub, since_aware, until_aware)
            if article:
                articles.append(article)

            if (i + 1) % 20 == 0:
                logger.info("%s: processed %d/%d articles, %d accepted",
                            self.source_name, i + 1, len(stubs), len(articles))
            if (i + 1) % 10 == 0:
                time.sleep(0.5)

        full_count = sum(1 for a in articles if len(a.raw_text) > 300)
        logger.info(
            "%s TOTAL: %d articles, %d with full text",
            self.source_name, len(articles), full_count,
        )
        return articles

    def _fetch_listings(self) -> list[dict]:
        """Fetch article stubs from listing pages."""
        stubs: list[dict] = []
        seen_links: set[str] = set()

        for listing_url in self.listing_urls:
            try:
                resp = self.session.get(listing_url, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("%s: listing %s failed: %s", self.source_name, listing_url, exc)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_found = 0

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]

                # Build absolute URL
                if href.startswith("/"):
                    full_url = urljoin(self.base_url, href)
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                # Check if it matches article URL pattern
                if not re.search(self.link_pattern, full_url):
                    continue

                if full_url in seen_links:
                    continue
                seen_links.add(full_url)

                title = a_tag.get_text(strip=True) or ""
                if len(title) < 5:
                    parent = a_tag.parent
                    if parent:
                        title = parent.get_text(strip=True)[:200]

                stubs.append({
                    "title": title[:200] if title else "",
                    "link": full_url,
                })
                page_found += 1

            logger.debug("%s: found %d links on %s", self.source_name, page_found, listing_url)
            time.sleep(0.3)

        return stubs

    def _fetch_article(
        self, stub: dict, since: datetime, until: datetime
    ) -> RawArticle | None:
        """Fetch and parse a single article page."""
        url = stub["link"]

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("%s: article fetch failed %s: %s", self.source_name, url, exc)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise
        for tag in soup.select("script, style, nav, header, footer, aside, iframe, noscript"):
            tag.decompose()

        # Extract date from page
        pub_dt = self._extract_page_date(soup)
        if pub_dt:
            pub_aware = _ensure_tz(pub_dt)
            if pub_aware > until or pub_aware < since:
                return None

        # Extract title
        title = stub.get("title", "")
        if not title or len(title) < 5:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Extract full text
        raw_text = self._extract_text(soup)

        if not raw_text and not title:
            return None

        # Extract tags
        tags = self._extract_tags(soup)

        return RawArticle(
            source=self.source_name,
            title=title or "(без заголовка)",
            link=url,
            published_at=pub_dt,
            raw_text=raw_text,
            native_tags=tags,
        )

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract article text using configured selectors + fallbacks."""
        # Source-specific selectors
        for selector in self.article_selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 150:
                    return text

        # Generic fallbacks
        for sel in (
            "[itemprop='articleBody']",
            "div.article__text",
            "div.article-body",
            "div.article__body",
            "div.text-content",
            "div.news-text",
            "article",
        ):
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 200:
                    return text

        # Smart fallback
        text = _extract_largest_text_block(soup)
        if text and len(text) > 200:
            return text

        return ""

    def _extract_page_date(self, soup: BeautifulSoup) -> datetime | None:
        """Try to extract publication date from article page."""
        # <meta property="article:published_time">
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "") or meta.get("name", "")
            if prop in ("article:published_time", "datePublished",
                        "og:article:published_time", "publish-date"):
                content = meta.get("content", "")
                if content:
                    dt = _parse_datetime(content)
                    if dt:
                        return dt

        # <time datetime="...">
        time_el = soup.find("time", attrs={"datetime": True})
        if time_el:
            dt = _parse_datetime(time_el["datetime"])
            if dt:
                return dt

        # [itemprop="datePublished"]
        dp = soup.find(attrs={"itemprop": "datePublished"})
        if dp:
            content = dp.get("content", "") or dp.get("datetime", "") or dp.get_text(strip=True)
            if content:
                dt = _parse_datetime(content)
                if dt:
                    return dt

        return None

    def _extract_tags(self, soup: BeautifulSoup) -> list[str]:
        tags = []
        # <meta property="article:tag">
        for meta in soup.find_all("meta", attrs={"property": "article:tag"}):
            t = meta.get("content", "").strip()
            if t:
                tags.append(t)
        return tags


# ------------------------------------------------------------------
# Известия (iz.ru)
# ------------------------------------------------------------------

class IzvestiaScraper(_BaseNewsHtmlScraper):
    """Известия — федеральная ежедневная газета."""

    source_name = "izvestia"
    base_url = "https://iz.ru"
    listing_urls = [
        "https://iz.ru/news",
        "https://iz.ru/rubric/politika",
        "https://iz.ru/rubric/ekonomika",
        "https://iz.ru/rubric/obshchestvo",
        "https://iz.ru/rubric/proisshestviya",
    ]
    # iz.ru article URLs: /1234567/... or /news/... with date
    link_pattern = r"iz\.ru/\d{5,}"
    article_selectors = [
        "div.article__text",
        "div.text-article",
        "div.article_page__left__article__text",
        "div[itemprop='articleBody']",
        "div.article-body",
    ]


# ------------------------------------------------------------------
# Gazeta.ru
# ------------------------------------------------------------------

class GazetaScraper(_BaseNewsHtmlScraper):
    """Gazeta.ru — общественно-политическое интернет-издание.

    Gazeta.ru frequently changes URL formats.
    Uses broad link matching + multiple discovery methods.
    """

    source_name = "gazeta"
    base_url = "https://www.gazeta.ru"
    listing_urls = [
        "https://www.gazeta.ru/",
        "https://www.gazeta.ru/last.shtml",
        "https://www.gazeta.ru/politics/",
        "https://www.gazeta.ru/business/",
        "https://www.gazeta.ru/social/",
        "https://www.gazeta.ru/tech/",
        "https://www.gazeta.ru/science/",
        "https://www.gazeta.ru/culture/",
        "https://www.gazeta.ru/sport/",
        "https://www.gazeta.ru/army/",
    ]
    # Broad pattern: any path with a section name + deeper path
    # Excludes root section pages, tag pages, author pages
    link_pattern = r"gazeta\.ru/[a-z]+/.+"
    article_selectors = [
        "div.article_text_body",
        "div.maintext",
        "div[itemprop='articleBody']",
        "div.b-text",
        "div.article-text",
        "div.item_text",
        "div.article__text",
    ]

    # URLs to exclude (not articles)
    _exclude_patterns = re.compile(
        r"(/tag/|/author/|/person/|/spec/|/special/|/rubric/|/about/|/adv/|"
        r"/\?|#|\.css|\.js|\.png|\.jpg|/rss|/export/|/feed)"
    )

    def _fetch_listings(self) -> list[dict]:
        """Override: use broader link discovery + log findings."""
        stubs: list[dict] = []
        seen_links: set[str] = set()

        for listing_url in self.listing_urls:
            try:
                resp = self.session.get(listing_url, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("gazeta: listing %s failed: %s", listing_url, exc)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_found = 0

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]

                # Build absolute URL
                if href.startswith("/"):
                    full_url = f"https://www.gazeta.ru{href}"
                elif href.startswith("http") and "gazeta.ru" in href:
                    full_url = href
                else:
                    continue

                # Exclude non-article URLs
                if self._exclude_patterns.search(full_url):
                    continue

                # Must be deeper than just /section/
                path = full_url.split("gazeta.ru")[-1]
                parts = [p for p in path.split("/") if p]
                if len(parts) < 2:
                    continue

                if full_url in seen_links:
                    continue
                seen_links.add(full_url)

                title = a_tag.get_text(strip=True) or ""
                if len(title) < 5:
                    parent = a_tag.parent
                    if parent:
                        title = parent.get_text(strip=True)[:200]

                stubs.append({
                    "title": title[:200] if title else "",
                    "link": full_url,
                })
                page_found += 1

            logger.info("gazeta: found %d links on %s", page_found, listing_url)
            time.sleep(0.3)

        return stubs


# ------------------------------------------------------------------
# Экспресс газета (eg.ru)
# ------------------------------------------------------------------

class EgScraper(_BaseNewsHtmlScraper):
    """Экспресс газета — развлекательное издание."""

    source_name = "eg"
    base_url = "https://eg.ru"
    listing_urls = [
        "https://eg.ru/",
        "https://eg.ru/showbusiness/",
        "https://eg.ru/society/",
        "https://eg.ru/politics/",
    ]
    # eg.ru articles: /category/slug-12345/ or /slug-12345/
    link_pattern = r"eg\.ru/.+/.+-\d+"
    article_selectors = [
        "div.article__text",
        "div.post-content",
        "div.entry-content",
        "div[itemprop='articleBody']",
        "div.article-body",
    ]
