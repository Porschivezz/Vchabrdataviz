"""VC.ru scraper using the public JSON API — date-range based."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle

logger = logging.getLogger(__name__)

VC_API_BASE = "https://api.vc.ru/v2.8"
MAX_PAGES = 100  # safety limit


class VcScraper(BaseScraper):
    """Fetches all VC.ru articles within a given date range."""

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

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = self._ensure_tz(since)
        until_aware = self._ensure_tz(until) if until else datetime.now(timezone.utc)

        articles: list[RawArticle] = []
        last_id: int | None = None
        reached_boundary = False

        for page_num in range(MAX_PAGES):
            params: dict = {"count": 20}
            if last_id is not None:
                params["last_id"] = last_id

            # Try /timeline first, fall back to /feed if it fails
            endpoint = f"{VC_API_BASE}/timeline"

            try:
                resp = self.session.get(endpoint, params=params, timeout=self.timeout)
                if resp.status_code == 404:
                    resp = self.session.get(
                        f"{VC_API_BASE}/feed", params=params, timeout=self.timeout
                    )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("VC.ru API request failed: %s", exc)
                break

            # Log raw structure on first page to help diagnose format issues
            if page_num == 0:
                result_type = type(data.get("result")).__name__
                result_keys = (
                    list(data.get("result", {}).keys())
                    if isinstance(data.get("result"), dict)
                    else "—"
                )
                logger.info(
                    "VC.ru API response keys: %s, result type: %s, result keys: %s",
                    list(data.keys()),
                    result_type,
                    result_keys,
                )

            result = data.get("result", {})
            if isinstance(result, list):
                items = result
                next_last_id = None
            elif isinstance(result, dict):
                # Handle both "items" and "data" sub-keys
                items = result.get("items", result.get("data", []))
                next_last_id = result.get("last_id", result.get("lastId"))
            else:
                logger.warning("VC.ru: unexpected result type: %s, data=%r", type(result), str(data)[:300])
                break

            if not items:
                logger.info("VC.ru: empty items on page %d (result keys: %s)", page_num, list(result.keys()) if isinstance(result, dict) else type(result))
                break

            for item in items:
                if not isinstance(item, dict):
                    continue

                pub_dt = self._extract_date(item)

                if pub_dt is not None:
                    pub_aware = self._ensure_tz(pub_dt)
                    if pub_aware > until_aware:
                        continue  # too new, keep going
                    if pub_aware < since_aware:
                        reached_boundary = True
                        break

                article = self._parse_entry(item)
                if article is not None:
                    articles.append(article)

            if reached_boundary:
                break

            # Pagination
            if next_last_id is not None:
                if next_last_id == last_id:
                    break
                last_id = next_last_id
            elif items:
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

        logger.info(
            "VC.ru: fetched %d articles in range %s – %s (pages: %d)",
            len(articles), since_aware.date(), until_aware.date(), page_num + 1,
        )
        return articles

    # ------------------------------------------------------------------

    def _extract_date(self, entry: dict) -> datetime | None:
        return self._parse_date(entry.get("date", entry.get("date_rfc")))

    def _parse_entry(self, entry: dict) -> RawArticle | None:
        try:
            entry_id = entry.get("id", "")
            title = entry.get("title", "").strip()
            link = entry.get("url", f"https://vc.ru/p/{entry_id}")

            published_at = self._extract_date(entry)
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

        if not parts:
            entry_content = entry.get("entryContent", {})
            if isinstance(entry_content, dict):
                html_body = entry_content.get("html", "")
                if html_body:
                    parts.append(self._html_to_text(html_body))

        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

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
