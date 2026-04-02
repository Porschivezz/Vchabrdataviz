"""ТАСС (tass.ru) — dedicated scraper.

TASS RSS feed gives only short descriptions (~80-100 chars).
This scraper fetches the full article text from each page using
multiple selector strategies and a smart fallback.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.scrapers.rss_scraper import _ensure_tz, _parse_datetime, _extract_largest_text_block
from src.core.config import settings

logger = logging.getLogger(__name__)

# TASS article body selectors (multiple layouts)
TASS_SELECTORS = [
    "div.text-block",
    "div.text-content",
    "div.news-header__lead",
    "article.news-text",
    "div.news-article__text",
    "div[itemprop='articleBody']",
    "article",
]


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
            "Accept-Encoding": "gzip, deflate, br",
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

        # Step 2: Fetch full text for each article
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
                time.sleep(0.3)

        full_count = sum(1 for a in articles if len(a.raw_text) > 300)
        logger.info(
            "TASS TOTAL: %d articles, %d with full text",
            len(articles), full_count,
        )
        return articles

    def _fetch_rss(self, since: datetime, until: datetime) -> list[dict]:
        """Fetch article stubs from TASS RSS feed."""
        stubs: list[dict] = []

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

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        if not items:
            soup = BeautifulSoup(resp.content, "html.parser")
            items = soup.find_all("item")

        seen_links: set[str] = set()
        for item in items:
            link_el = item.find("link")
            link = ""
            if link_el:
                link = link_el.get_text(strip=True)
                if not link:
                    link = link_el.get("href", "")
            if not link:
                guid_el = item.find("guid")
                if guid_el:
                    g = guid_el.get_text(strip=True)
                    if g.startswith("http"):
                        link = g
            if not link or link in seen_links:
                continue

            pub_dt = None
            for tag in ("pubDate", "published", "updated"):
                el = item.find(tag)
                if el:
                    pub_dt = _parse_datetime(el.get_text(strip=True))
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
                desc_text = desc_el.string or desc_el.get_text(strip=True)
                if desc_text:
                    if "<" in desc_text:
                        description = BeautifulSoup(desc_text, "html.parser").get_text(separator="\n", strip=True)
                    else:
                        description = desc_text.strip()

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

        # Try TASS-specific selectors
        for selector in TASS_SELECTORS:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 150:
                    return text

        # Try collecting all <p> inside the main content area
        # TASS often has multiple div.text-block elements
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

        # Last resort: all <p> tags in body
        body = soup.find("body")
        if body:
            paragraphs = body.find_all("p")
            p_text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
            if len(p_text) > 200:
                return p_text

        return ""
