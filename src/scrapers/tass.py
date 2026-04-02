"""ТАСС (tass.ru) — dedicated scraper.

Uses RSS for article discovery + per-article page fetch for full text.
Falls back to HTML listing page scraping if RSS fails.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.scrapers.rss_scraper import _ensure_tz, _parse_datetime, _extract_largest_text_block
from src.core.config import settings

logger = logging.getLogger(__name__)


class TassScraper(BaseScraper):
    """ТАСС — полный парсер с извлечением текстов статей."""

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
            "Referer": "https://tass.ru/",
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

        # Step 1: Get article stubs from RSS
        stubs = self._fetch_rss(since_aware, until_aware)
        logger.info("TASS: %d stubs from RSS", len(stubs))

        # Step 2: If RSS gave nothing, try HTML listing pages
        if not stubs:
            logger.info("TASS: RSS empty, trying HTML listing pages")
            stubs = self._fetch_html_listing(since_aware, until_aware)
            logger.info("TASS: %d stubs from HTML listing", len(stubs))

        # Step 3: Fetch full text for each article
        articles: list[RawArticle] = []
        for i, stub in enumerate(stubs):
            full_text = self._fetch_article_text(stub["link"])

            raw_text = full_text if full_text else stub.get("description", "")
            if not raw_text and not stub["title"]:
                continue

            articles.append(RawArticle(
                source="tass",
                title=stub["title"],
                link=stub["link"],
                published_at=stub.get("published_at"),
                raw_text=raw_text,
                native_tags=stub.get("tags", []),
            ))

            if (i + 1) % 20 == 0:
                logger.info("TASS: enriched %d/%d articles", i + 1, len(stubs))
            # Be polite
            if (i + 1) % 10 == 0:
                time.sleep(0.5)

        full_count = sum(1 for a in articles if len(a.raw_text) > 300)
        logger.info(
            "TASS TOTAL: %d articles, %d with full text",
            len(articles), full_count,
        )
        return articles

    # ------------------------------------------------------------------
    # RSS fetching
    # ------------------------------------------------------------------

    def _fetch_rss(self, since: datetime, until: datetime) -> list[dict]:
        """Fetch article stubs from TASS RSS feed."""
        resp = None

        for attempt in range(3):
            try:
                resp = self.session.get(
                    "https://tass.ru/rss/v2.xml",
                    timeout=self.timeout,
                )
                if resp.status_code == 429:
                    time.sleep(2 ** attempt * 2)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                logger.error("TASS RSS failed: %s", exc)
                return []

        if resp is None or resp.status_code != 200:
            return []

        # Try html.parser first — more reliable for RSS <link> extraction
        soup = BeautifulSoup(resp.content, "html.parser")
        items = soup.find_all("item")

        if not items:
            # Fallback to XML parser
            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")

        logger.info("TASS RSS: found %d items", len(items))
        if not items:
            return []

        stubs: list[dict] = []
        seen_links: set[str] = set()

        for item in items:
            # Extract link — try multiple approaches
            link = self._extract_link_from_item(item)
            if not link or link in seen_links:
                continue

            pub_dt = None
            for tag_name in ("pubDate", "pubdate", "published", "updated"):
                el = item.find(tag_name)
                if el:
                    text = el.get_text(strip=True)
                    if text:
                        pub_dt = _parse_datetime(text)
                        if pub_dt:
                            break

            if pub_dt:
                pub_aware = _ensure_tz(pub_dt)
                if pub_aware > until or pub_aware < since:
                    continue

            seen_links.add(link)

            title_el = item.find("title")
            title = title_el.get_text(strip=True) if title_el else ""

            desc_el = item.find("description")
            description = ""
            if desc_el:
                desc_raw = desc_el.string or desc_el.get_text(strip=True)
                if desc_raw:
                    if "<" in desc_raw:
                        description = BeautifulSoup(desc_raw, "html.parser").get_text(
                            separator="\n", strip=True
                        )
                    else:
                        description = desc_raw.strip()

            tags = []
            for cat in item.find_all("category"):
                t = cat.get("term", "") or cat.get_text(strip=True)
                if t:
                    tags.append(t)

            stubs.append({
                "title": title,
                "link": link,
                "published_at": pub_dt,
                "description": description,
                "tags": tags,
            })

        return stubs

    def _extract_link_from_item(self, item) -> str:
        """Extract article URL from RSS <item> — handles edge cases."""
        # Method 1: <link> text content
        link_el = item.find("link")
        if link_el:
            text = link_el.get_text(strip=True)
            if text and text.startswith("http"):
                return text
            # Sometimes link text is in .string or .next_sibling
            if link_el.string and str(link_el.string).strip().startswith("http"):
                return str(link_el.string).strip()
            # BS4 sometimes puts URL as next_sibling NavigableString
            if link_el.next_sibling:
                sib = str(link_el.next_sibling).strip()
                if sib.startswith("http"):
                    return sib
            href = link_el.get("href", "")
            if href:
                return href.strip()

        # Method 2: <guid> as URL
        guid_el = item.find("guid")
        if guid_el:
            g = guid_el.get_text(strip=True)
            if g.startswith("http"):
                return g

        return ""

    # ------------------------------------------------------------------
    # HTML listing fallback
    # ------------------------------------------------------------------

    def _fetch_html_listing(self, since: datetime, until: datetime) -> list[dict]:
        """Scrape TASS homepage/listing pages for article links."""
        stubs: list[dict] = []
        seen_links: set[str] = set()

        for section in ("", "/ekonomika", "/politika", "/obschestvo", "/mezhdunarodnaya-panorama"):
            url = f"https://tass.ru{section}"
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.debug("TASS listing %s failed: %s", url, exc)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find article links — TASS uses various link patterns
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                # TASS article URLs: /section/12345678 or /category/section/12345678
                if not re.match(r"^/[a-z-]+/\d{5,}$", href) and \
                   not re.match(r"^/[a-z-]+/[a-z-]+/\d{5,}$", href):
                    continue

                full_link = f"https://tass.ru{href}"
                if full_link in seen_links:
                    continue
                seen_links.add(full_link)

                title = a_tag.get_text(strip=True) or ""
                if len(title) < 5:
                    # Try parent element for title
                    parent = a_tag.parent
                    if parent:
                        title = parent.get_text(strip=True)

                stubs.append({
                    "title": title[:200] if title else "",
                    "link": full_link,
                    "published_at": None,
                    "description": "",
                    "tags": [],
                })

            time.sleep(0.3)

        return stubs

    # ------------------------------------------------------------------
    # Full text extraction
    # ------------------------------------------------------------------

    def _fetch_article_text(self, url: str) -> str:
        """Fetch full article text from a TASS article page."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("TASS: failed to fetch %s: %s", url, exc)
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise
        for tag in soup.select("script, style, nav, header, footer, aside, iframe, noscript"):
            tag.decompose()

        # TASS-specific selectors (try in priority order)
        for selector in (
            "div.text-block",
            "div.text-content",
            "article.news-text",
            "div.news-article__text",
            "div[itemprop='articleBody']",
            "div.ds_content",
        ):
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 150:
                    return text

        # Try collecting ALL div.text-block elements (TASS splits content)
        text_blocks = soup.select("div.text-block")
        if text_blocks:
            combined = "\n".join(
                block.get_text(separator="\n", strip=True)
                for block in text_blocks
            )
            if len(combined) > 150:
                return combined

        # Smart fallback: largest text-dense block
        text = _extract_largest_text_block(soup)
        if text and len(text) > 200:
            return text

        # Last resort: all substantial <p> tags in body
        body = soup.find("body")
        if body:
            paragraphs = body.find_all("p")
            p_text = "\n".join(
                p.get_text(strip=True)
                for p in paragraphs
                if len(p.get_text(strip=True)) > 30
            )
            if len(p_text) > 200:
                return p_text

        return ""
