"""VC.ru scraper using the public JSON API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)

VC_API_BASE = "https://api.vc.ru/v2.8"


class VcScraper(BaseScraper):
    """Fetches articles from VC.ru via its public API (``/v2.8``)."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; MonitorBot/1.0)",
            "Accept": "application/json",
        })

    def fetch_articles(self, *, limit: int = 20) -> list[RawArticle]:
        articles: list[RawArticle] = []
        last_id: int | None = None

        while len(articles) < limit:
            params: dict = {"count": min(limit - len(articles), 20)}
            if last_id is not None:
                params["lastId"] = last_id

            try:
                resp = self.session.get(
                    f"{VC_API_BASE}/timeline",
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("VC.ru API request failed: %s", exc)
                break

            items = data.get("result", data.get("items", []))
            if not items:
                break

            for item in items:
                if len(articles) >= limit:
                    break
                article = self._parse_entry(item)
                if article is not None:
                    articles.append(article)

            # Pagination: use the last item's ID
            if items:
                last_item = items[-1]
                last_id = last_item.get("id")
                if last_id is None:
                    break
            else:
                break

        logger.info("VC.ru: fetched %d articles", len(articles))
        return articles

    def _parse_entry(self, entry: dict) -> RawArticle | None:
        try:
            entry_id = entry.get("id", "")
            title = entry.get("title", "").strip()
            link = entry.get("url", f"https://vc.ru/p/{entry_id}")

            date_ts = entry.get("date", entry.get("dateRFC"))
            published_at = self._parse_date(date_ts)

            # VC API returns blocks-based body or html
            raw_text = self._extract_text(entry)

            # Subsites and tags
            tags: list[str] = []
            subsite = entry.get("subsite", {})
            if isinstance(subsite, dict) and subsite.get("name"):
                tags.append(subsite["name"])

            for tag_obj in entry.get("tags", []):
                if isinstance(tag_obj, dict):
                    tag_name = tag_obj.get("name", "")
                elif isinstance(tag_obj, str):
                    tag_name = tag_obj
                else:
                    continue
                if tag_name:
                    tags.append(tag_name)

            if not title and not raw_text:
                return None

            return RawArticle(
                source="vc",
                title=title or "(без заголовка)",
                link=link,
                published_at=published_at,
                raw_text=raw_text,
                native_tags=tags,
            )
        except Exception as exc:
            logger.warning("Failed to parse VC.ru entry: %s", exc)
            return None

    def _extract_text(self, entry: dict) -> str:
        # Try intro + blocks approach
        parts: list[str] = []

        intro = entry.get("intro", "")
        if intro:
            parts.append(self._html_to_text(intro) if "<" in intro else intro)

        # v2.8 returns blocks
        for block in entry.get("blocks", []):
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            bdata = block.get("data", {})
            if btype == "text" and isinstance(bdata, dict):
                text_val = bdata.get("text", "")
                parts.append(self._html_to_text(text_val) if "<" in text_val else text_val)
            elif btype == "header" and isinstance(bdata, dict):
                parts.append(bdata.get("text", ""))

        # Fallback: entryContent or html
        if not parts:
            html_body = entry.get("entryContent", {}).get("html", "")
            if html_body:
                parts.append(self._html_to_text(html_body))

        return "\n".join(p for p in parts if p)

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _parse_date(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None
