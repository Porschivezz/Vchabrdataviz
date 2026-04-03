"""ТАСС (tass.ru) — scraper for Russian VPS (direct access, no proxy).

Uses RSS feeds (including section-specific) for article discovery,
then fetches each article page and extracts text from <p> tags
inside known content containers.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from ru_collector.scrapers.base import BaseScraper, RawArticle
from ru_collector.scrapers.rss_scraper import _ensure_tz, _parse_datetime

logger = logging.getLogger(__name__)

TASS_HOME = "https://tass.ru"

RSS_FEEDS = [
    f"{TASS_HOME}/rss/v2.xml",
    f"{TASS_HOME}/rss/v2.xml?sections=MEhvM9YoKE4",  # Политика
    f"{TASS_HOME}/rss/v2.xml?sections=T1BvM9YCjLk",  # Экономика
    f"{TASS_HOME}/rss/v2.xml?sections=SurvM9YC7RI",  # Общество
    f"{TASS_HOME}/rss/v2.xml?sections=QE5vM9YCE3M",  # Мир
    f"{TASS_HOME}/rss/v2.xml?sections=vDFvM9Ycjuk",  # Наука
]

EXCLUDED_PREFIXES = (
    "/info/", "/tag/", "/author/", "/search", "/spec/",
    "/press/", "/podcasts/", "/video/", "/photo/", "/rss",
)


def _is_article_url(href: str) -> bool:
    if not href.startswith(TASS_HOME):
        return False
    path = href[len(TASS_HOME):]
    if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    return bool(re.match(r"^/[\w-]+(/[\w-]+)?/\d+$", path))


class TassScraper(BaseScraper):
    """ТАСС — runs directly from Russian VPS, no proxy needed."""

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

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = _ensure_tz(since)
        until_aware = _ensure_tz(until) if until else datetime.now(timezone.utc)

        discovered = self._discover_from_rss(since_aware, until_aware)
        logger.info("TASS: discovered %d article URLs from RSS", len(discovered))

        if not discovered:
            discovered = self._discover_from_html(since_aware, until_aware)
            logger.info("TASS: discovered %d URLs from HTML listing", len(discovered))

        articles: list[RawArticle] = []
        for i, stub in enumerate(discovered):
            article = self._parse_article(stub, since_aware, until_aware)
            if article:
                articles.append(article)

            if (i + 1) % 20 == 0:
                logger.info("TASS: parsed %d/%d, accepted %d",
                            i + 1, len(discovered), len(articles))
            if (i + 1) % 5 == 0:
                time.sleep(0.3)

        full_count = sum(1 for a in articles if len(a.raw_text) > 300)
        logger.info("TASS TOTAL: %d articles, %d with full text", len(articles), full_count)
        return articles

    # ------------------------------------------------------------------
    # Article discovery
    # ------------------------------------------------------------------

    def _discover_from_rss(self, since: datetime, until: datetime) -> list[dict]:
        stubs: list[dict] = []
        seen: set[str] = set()

        for feed_url in RSS_FEEDS:
            try:
                resp = self.session.get(feed_url, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.debug("TASS RSS %s failed: %s", feed_url, exc)
                continue

            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")
            if not items:
                soup = BeautifulSoup(resp.content, "html.parser")
                items = soup.find_all("item")

            for item in items:
                link = ""
                link_el = item.find("link")
                if link_el:
                    link = (link_el.get_text(strip=True)
                            or (link_el.string and str(link_el.string).strip())
                            or "")
                if not link:
                    if link_el and link_el.next_sibling:
                        sib = str(link_el.next_sibling).strip()
                        if sib.startswith("http"):
                            link = sib
                if not link:
                    guid_el = item.find("guid")
                    if guid_el:
                        g = guid_el.get_text(strip=True)
                        if g.startswith("http"):
                            link = g

                if not link or not _is_article_url(link) or link in seen:
                    continue
                seen.add(link)

                pub_dt = None
                for tag_name in ("pubDate", "published", "updated"):
                    el = item.find(tag_name)
                    if el and el.get_text(strip=True):
                        pub_dt = _parse_datetime(el.get_text(strip=True))
                        if pub_dt:
                            break

                if pub_dt:
                    pub_aware = _ensure_tz(pub_dt)
                    if pub_aware > until or pub_aware < since:
                        continue

                title_el = item.find("title")
                title = title_el.get_text(strip=True) if title_el else ""

                stubs.append({"link": link, "title": title, "published_at": pub_dt})

            time.sleep(0.2)

        return stubs

    def _discover_from_html(self, since: datetime, until: datetime) -> list[dict]:
        stubs: list[dict] = []
        seen: set[str] = set()

        sections = [
            "", "/ekonomika", "/politika", "/obschestvo",
            "/mezhdunarodnaya-panorama", "/nauka",
        ]
        for section in sections:
            url = f"{TASS_HOME}{section}"
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/"):
                    href = f"{TASS_HOME}{href}"
                if not _is_article_url(href) or href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                stubs.append({"link": href, "title": title[:200], "published_at": None})

            time.sleep(0.3)

        return stubs

    # ------------------------------------------------------------------
    # Article parsing
    # ------------------------------------------------------------------

    def _parse_article(self, stub: dict, since: datetime, until: datetime) -> RawArticle | None:
        url = stub["link"]

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("TASS article %s failed: %s", url, exc)
            return None

        # If page is too small (JS shell / SPA), retry with Googlebot UA
        if len(resp.text) < 5000:
            try:
                resp2 = self.session.get(
                    url, timeout=self.timeout,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
                )
                if resp2.status_code == 200 and len(resp2.text) > len(resp.text):
                    resp = resp2
            except requests.RequestException:
                pass

        soup = BeautifulSoup(resp.text, "html.parser")

        # --- Title ---
        title = stub.get("title", "")
        if not title:
            for sel in ("h1.news-header__title", "h1[class*='title']", "h1"):
                h1 = soup.select_one(sel)
                if h1 and h1.get_text(strip=True):
                    title = h1.get_text(strip=True)
                    break
            if not title:
                og = soup.find("meta", attrs={"property": "og:title"})
                if og:
                    title = og.get("content", "")

        # --- Lead ---
        lead = ""
        for sel in ("div.news-header__lead", "div[class*='lead']", "p.lead"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                lead = el.get_text(strip=True)
                break

        # --- Body text ---
        paragraphs: list[str] = []

        for container_sel in (
            "div.text-content",
            "div.news-body",
            "div[class*='NewsBody']",
            "article",
            "div[class*='text']",
        ):
            container = soup.select_one(container_sel)
            if not container:
                continue

            for p in container.find_all("p"):
                parent = p.parent
                if parent:
                    parent_class = " ".join(parent.get("class", []))
                    if any(x in parent_class.lower() for x in
                           ("caption", "promo", "advert", "related", "banner")):
                        continue

                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    paragraphs.append(text)

            if paragraphs:
                break

        body_text = "\n\n".join(paragraphs)

        # --- Fallback: JSON-LD articleBody ---
        if not body_text or len(body_text) < 100:
            for script in soup.find_all("script", type="application/ld+json"):
                if not script.string:
                    continue
                try:
                    data = json.loads(script.string)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if isinstance(item, dict):
                            ab = item.get("articleBody", "")
                            if ab and len(ab) > len(body_text):
                                body_text = ab
                except (json.JSONDecodeError, KeyError):
                    continue

        if lead and lead not in body_text:
            body_text = f"{lead}\n\n{body_text}" if body_text else lead

        # --- Date ---
        pub_dt = stub.get("published_at")
        if not pub_dt:
            pub_dt = self._extract_date(soup)

        if pub_dt:
            pub_aware = _ensure_tz(pub_dt)
            if pub_aware > until or pub_aware < since:
                return None

        if not title and not body_text:
            return None

        # --- Tags ---
        tags: list[str] = []
        for a in soup.select("a[href*='/tag/'], div.tags a"):
            t = a.get_text(strip=True)
            if t:
                tags.append(t)

        m = re.search(r"tass\.ru/([\w-]+)/", url)
        if m:
            tags.insert(0, m.group(1))

        return RawArticle(
            source="tass",
            title=title or "(без заголовка)",
            link=url,
            published_at=pub_dt,
            raw_text=body_text,
            native_tags=tags,
        )

    def _extract_date(self, soup: BeautifulSoup) -> datetime | None:
        time_el = soup.find("time", attrs={"datetime": True})
        if time_el:
            dt = _parse_datetime(time_el["datetime"])
            if dt:
                return dt

        for sel in (
            "span.news-header__date",
            "div.news-header__date",
            "span[class*='Date_text']",
            "span[class*='date']",
        ):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                dt = _parse_datetime(el.get_text(strip=True))
                if dt:
                    return dt

        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if meta:
            dt = _parse_datetime(meta.get("content", ""))
            if dt:
                return dt

        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    for key in ("datePublished", "dateCreated", "dateModified"):
                        if key in data:
                            dt = _parse_datetime(data[key])
                            if dt:
                                return dt
            except (json.JSONDecodeError, KeyError):
                continue

        return None
