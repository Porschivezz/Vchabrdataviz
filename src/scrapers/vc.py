"""VC.ru scraper using the public JSON API — date-range based.

Collects ALL publications within the date range by paginating
through /timeline with sorting=date (newest → oldest).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime as _parse_rfc2822

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.core.config import settings

logger = logging.getLogger(__name__)

VC_API_BASE = "https://api.vc.ru/v2.8"

# 2000+ entries/day ÷ 50/page = 40+ pages/day; for 30-day range need ~1200
MAX_PAGES = 1500
ITEMS_PER_PAGE = 50  # max the API typically allows


class VcScraper(BaseScraper):
    """Fetches ALL VC.ru entries within a date range.

    VC.ru /timeline items are wrapped: ``{"data": {article fields}, ...}``.
    Pagination uses ``lastId`` + ``lastSortingValue`` cursors.
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
        proxy_url = settings.scraper_proxy_url.strip()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def fetch_articles(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[RawArticle]:
        since_aware = self._ensure_tz(since)
        until_aware = self._ensure_tz(until) if until else datetime.now(timezone.utc)

        articles: list[RawArticle] = []
        seen_ids: set[int | str] = set()
        last_sorting_value: str | int | None = None
        last_id: int | None = None

        consecutive_old_pages = 0  # require 3 consecutive all-old pages to stop
        stall_count = 0  # detect cursor not advancing

        for page_num in range(MAX_PAGES):
            params: dict = {
                "count": ITEMS_PER_PAGE,
                "sorting": "date",
            }
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
                logger.error("VC.ru API page %d failed: %s", page_num, exc)
                # Brief pause and retry once
                time.sleep(1)
                try:
                    resp = self.session.get(
                        f"{VC_API_BASE}/timeline",
                        params=params,
                        timeout=self.timeout,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except requests.RequestException:
                    logger.error("VC.ru API page %d retry failed, stopping", page_num)
                    break

            result = data.get("result", {})
            if not isinstance(result, dict):
                logger.warning("VC.ru: result is not a dict: %s", type(result))
                break

            raw_items = result.get("items", [])
            new_last_id = result.get("lastId")
            new_last_sorting = result.get("lastSortingValue")

            # Log first page structure
            if page_num == 0:
                logger.info(
                    "VC.ru page 0: %d items, lastId=%s, lastSortingValue=%s",
                    len(raw_items), new_last_id, new_last_sorting,
                )
                if raw_items and isinstance(raw_items[0], dict):
                    first_raw = raw_items[0]
                    logger.info("VC.ru first raw item keys: %s", sorted(first_raw.keys()))
                    first_data = first_raw.get("data", first_raw)
                    if isinstance(first_data, dict):
                        for k in ("date", "dateRFC", "title"):
                            if k in first_data:
                                logger.info("VC.ru item[0].data.%s = %r", k, str(first_data[k])[:120])

            if not raw_items:
                logger.info("VC.ru: empty page %d, stopping", page_num)
                break

            # Process items
            page_in_range = 0
            page_too_old = 0
            page_too_new = 0

            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue

                entry = raw_item.get("data", raw_item)
                if not isinstance(entry, dict):
                    continue

                # Deduplicate
                eid = entry.get("id")
                if eid is not None and eid in seen_ids:
                    continue
                if eid is not None:
                    seen_ids.add(eid)

                pub_dt = self._extract_date(entry)

                if pub_dt is not None:
                    pub_aware = self._ensure_tz(pub_dt)
                    if pub_aware > until_aware:
                        page_too_new += 1
                        continue
                    if pub_aware < since_aware:
                        page_too_old += 1
                        continue

                page_in_range += 1
                article = self._parse_entry(entry)
                if article is not None:
                    articles.append(article)

            # Track consecutive all-old pages to confirm we've left the range
            if page_too_old > 0 and page_in_range == 0 and page_too_new == 0:
                consecutive_old_pages += 1
            else:
                consecutive_old_pages = 0

            if consecutive_old_pages >= 3:
                logger.info("VC.ru: 3 consecutive all-old pages, stopping at page %d", page_num)
                break

            # Progress logging every 10 pages
            if (page_num + 1) % 10 == 0:
                logger.info(
                    "VC.ru page %d: collected %d articles so far "
                    "(this page: %d in range, %d old, %d new)",
                    page_num, len(articles), page_in_range, page_too_old, page_too_new,
                )

            # Advance pagination cursor
            cursor_advanced = False
            if new_last_sorting is not None and new_last_sorting != last_sorting_value:
                last_sorting_value = new_last_sorting
                last_id = new_last_id
                cursor_advanced = True
            elif new_last_id is not None and new_last_id != last_id:
                last_id = new_last_id
                cursor_advanced = True

            if not cursor_advanced:
                stall_count += 1
                if stall_count >= 3:
                    logger.warning(
                        "VC.ru: cursor stalled for 3 pages at lastId=%s, stopping", last_id,
                    )
                    break
                # Try to unstall by using just lastId from last item
                if raw_items:
                    fallback_entry = raw_items[-1]
                    if isinstance(fallback_entry, dict):
                        fb_data = fallback_entry.get("data", fallback_entry)
                        if isinstance(fb_data, dict) and fb_data.get("id"):
                            last_id = fb_data["id"]
                            last_sorting_value = new_last_sorting
            else:
                stall_count = 0

        logger.info(
            "VC.ru TOTAL: %d articles in range %s – %s (pages: %d, seen IDs: %d)",
            len(articles), since_aware.date(), until_aware.date(),
            page_num + 1, len(seen_ids),
        )
        return articles

    # ------------------------------------------------------------------

    def _extract_date(self, entry: dict) -> datetime | None:
        for field in ("date", "dateRFC", "last_modification_date"):
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

        if not parts:
            entry_content = entry.get("entryContent", {})
            if isinstance(entry_content, dict):
                html_body = entry_content.get("html", "")
                if html_body:
                    parts.append(self._html_to_text(html_body))

        return "\n".join(p for p in parts if p)

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
            if value > 1e12:
                value = value / 1000.0
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc)
            except (OSError, ValueError):
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
            try:
                return _parse_rfc2822(value)
            except Exception:
                pass
            try:
                ts = float(value)
                if ts > 1e12:
                    ts = ts / 1000.0
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError):
                pass
        return None
