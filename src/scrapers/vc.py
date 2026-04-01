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
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://vc.ru/",
        })

    def fetch_articles(self, *, limit: int = 20) -> list[RawArticle]:
        articles: list[RawArticle] = []
        last_id: int | None = None

        while len(articles) < limit:
            params: dict = {"count": min(limit - len(articles), 20), "allSite": 1}
            if last_id is not None:
                params["last_id"] = last_id

            try:
                resp = self.session.get(
                    f"{VC_API_BASE}/feed",
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("VC.ru API request failed: %s", exc)
                break

            # VC.ru response: {"result": {"items": [...], "last_id": N}}
            # or {"result": [...]}  — handle both
            result = data.get("result", {})
            if isinstance(result, list):
                items = result
                next_last_id = None
            elif isinstance(result, dict):
                items = result.get("items", [])
                next_last_id = result.get("last_id")
            else:
                logger.warning("VC.ru: unexpected result type: %s", type(result))
                break

            if not items:
                logger.info("VC.ru: no more items")
                break

            for item in items:
                if not isinstance(item, dict):
                    logger.debug("VC.ru: skipping non-dict item: %r", item)
                    continue
                if len(articles) >= limit:
                    break
                article = self._parse_entry(item)
                if article is not None:
                    articles.append(article)

            # Pagination
            if next_last_id is not None:
                if next_last_id == last_id:
                    break  # no progress
                last_id = next_last_id
            elif items:
                # Fall back: use last item's id
                last_item = items[-1]
                if isinstance(last_item, dict):
                    new_id = last_item.get("id")
                    if new_id is None or new_id == last_id:
                        break
                    last_id = new_id
                else:
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

            date_ts = entry.get("date", entry.get("date_rfc"))
            published_at = self._parse_date(date_ts)

            raw_text = self._extract_text(entry)

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
        parts: list[str] = []

        intro = entry.get("intro", "")
        if intro:
            parts.append(self._html_to_text(intro) if "<" in intro else intro)

        # Blocks-based content
        for block in entry.get("blocks", []):
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            bdata = block.get("data", {})
            if not isinstance(bdata, dict):
                continue
            if btype in ("text", "header"):
                text_val = bdata.get("text", "")
                if text_val:
                    parts.append(
                        self._html_to_text(text_val) if "<" in text_val else text_val
                    )

        # Fallback: entryContent
        if not parts:
            entry_content = entry.get("entryContent", {})
            if isinstance(entry_content, dict):
                html_body = entry_content.get("html", "")
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
