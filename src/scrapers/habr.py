"""Habr.com scraper using the unofficial JSON API."""

from __future__ import annotations

import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)

HABR_API_BASE = "https://habr.com/kek/v2"


class HabrScraper(BaseScraper):
    """Fetches articles from Habr via its internal JSON API (``/kek/v2``)."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; MonitorBot/1.0)",
            "Accept": "application/json",
        })

    def fetch_articles(self, *, limit: int = 20) -> list[RawArticle]:
        articles: list[RawArticle] = []
        page = 1
        per_page = min(limit, 20)

        while len(articles) < limit:
            try:
                resp = self.session.get(
                    f"{HABR_API_BASE}/articles",
                    params={
                        "fl": "ru",
                        "hl": "ru",
                        "page": page,
                        "perPage": per_page,
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("Habr API request failed (page %d): %s", page, exc)
                break

            article_ids = data.get("articleIds", [])
            articles_map = data.get("articleRefs", {})

            if not article_ids:
                break

            for aid in article_ids:
                if len(articles) >= limit:
                    break

                ref = articles_map.get(str(aid))
                if ref is None:
                    continue

                article = self._parse_article_ref(ref)
                if article is not None:
                    articles.append(article)

            page += 1

        logger.info("Habr: fetched %d articles", len(articles))
        return articles

    def _parse_article_ref(self, ref: dict) -> RawArticle | None:
        try:
            aid = ref.get("id", "")
            title = ref.get("titleHtml", ref.get("title", "")).strip()
            link = f"https://habr.com/ru/articles/{aid}/"

            pub_str = ref.get("timePublished", "")
            published_at = self._parse_datetime(pub_str)

            # textHtml contains full body in the listing response
            body_html = ref.get("textHtml", "")
            if not body_html:
                # Fall back to fetching the individual article
                body_html = self._fetch_full_body(aid)

            raw_text = self._html_to_text(body_html)

            hubs = ref.get("hubs", [])
            tags = [h.get("title", h.get("alias", "")) for h in hubs if isinstance(h, dict)]
            # Also include explicit tags if present
            for flow in ref.get("flows", []):
                if isinstance(flow, dict) and flow.get("title"):
                    tags.append(flow["title"])

            return RawArticle(
                source="habr",
                title=title,
                link=link,
                published_at=published_at,
                raw_text=raw_text,
                native_tags=tags,
            )
        except Exception as exc:
            logger.warning("Failed to parse Habr article ref: %s", exc)
            return None

    def _fetch_full_body(self, article_id: str) -> str:
        try:
            resp = self.session.get(
                f"{HABR_API_BASE}/articles/{article_id}",
                params={"fl": "ru", "hl": "ru"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("article", {}).get("textHtml", "")
        except requests.RequestException as exc:
            logger.warning("Habr: failed to fetch full body for %s: %s", article_id, exc)
            return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _parse_datetime(s: str) -> datetime | None:
        if not s:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                continue
        return None
