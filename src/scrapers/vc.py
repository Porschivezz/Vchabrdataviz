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
    """Fetches all VC.ru articles within a given date range.

    The VC.ru /timeline API returns items wrapped in a ``data`` envelope::

        { "id": ..., "type": ..., "data": { <actual article fields> } }

    All article fields (title, date, blocks, etc.) live inside ``data``.
    """

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
        last_sorting_value: str | int | None = None
        last_id: int | None = None
        reached_boundary = False

        for page_num in range(MAX_PAGES):
            params: dict = {"count": 20, "allSite": "true", "sorting": "date"}
            if last_sorting_value is not None:
                params["lastSortingValue"] = last_sorting_value
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

            result = data.get("result", {})
            if not isinstance(result, dict):
                logger.warning("VC.ru: result is not a dict: %s", type(result))
                break

            raw_items = result.get("items", [])
            new_last_id = result.get("lastId")
            new_last_sorting = result.get("lastSortingValue")

            if page_num == 0:
                logger.info(
                    "VC.ru page 0: %d raw items, lastId=%s, lastSortingValue=%s",
                    len(raw_items), new_last_id, new_last_sorting,
                )
                if raw_items and isinstance(raw_items[0], dict):
                    first_raw = raw_items[0]
                    logger.info(
                        "VC.ru first raw item keys: %s", sorted(first_raw.keys()),
                    )
                    # Unwrap and log the actual article data
                    first_data = first_raw.get("data", first_raw)
                    if isinstance(first_data, dict):
                        logger.info(
                            "VC.ru first item data keys: %s", sorted(first_data.keys()),
                        )
                        for k in ("date", "dateRFC", "title", "url"):
                            if k in first_data:
                                val = first_data[k]
                                logger.info("VC.ru first item data.%s = %r", k, str(val)[:120])

            if not raw_items:
                logger.info("VC.ru: no items on page %d", page_num)
                break

            # Unwrap items: each item has {"data": {actual article}, ...}
            page_too_old_count = 0
            page_total = 0

            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue

                # Unwrap the data envelope
                entry = raw_item.get("data", raw_item)
                if not isinstance(entry, dict):
                    continue

                page_total += 1
                pub_dt = self._extract_date(entry)

                if pub_dt is not None:
                    pub_aware = self._ensure_tz(pub_dt)
                    if pub_aware > until_aware:
                        continue  # too new, keep going
                    if pub_aware < since_aware:
                        page_too_old_count += 1
                        continue  # too old, skip but count

                article = self._parse_entry(entry)
                if article is not None:
                    articles.append(article)

            # Stop when entire page is older than range
            if page_total > 0 and page_too_old_count == page_total:
                reached_boundary = True

            if reached_boundary:
                break

            # Pagination via lastSortingValue + lastId
            if new_last_sorting is not None and new_last_sorting != last_sorting_value:
                last_sorting_value = new_last_sorting
                last_id = new_last_id
            elif new_last_id is not None and new_last_id != last_id:
                last_id = new_last_id
            else:
                break

        logger.info(
            "VC.ru: fetched %d articles in range %s – %s (pages: %d)",
            len(articles), since_aware.date(), until_aware.date(), page_num + 1,
        )
        return articles

    # ------------------------------------------------------------------

    def _extract_date(self, entry: dict) -> datetime | None:
        """Try multiple date fields; handle seconds and milliseconds."""
        for field in ("date", "dateRFC", "date_rfc", "last_modification_date"):
            val = entry.get(field)
            if val is not None:
                parsed = self._parse_date(val)
                if parsed is not None:
                    return parsed
        return None

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

        # Fallback: entryContent HTML
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
            # Handle both seconds and milliseconds timestamps
            if value > 1e12:
                value = value / 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
            # Try RFC 2822 via email.utils
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(value)
            except Exception:
                pass
            # Try as numeric string
            try:
                ts = float(value)
                if ts > 1e12:
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError):
                pass
        return None
