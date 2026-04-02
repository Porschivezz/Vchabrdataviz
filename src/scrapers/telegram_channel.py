"""Telegram channel scraper — fetches posts from public Telegram channels.

Uses the public web preview at t.me/s/{channel} which provides
an HTML page with recent messages, no API key needed.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, RawArticle
from src.core.config import settings

logger = logging.getLogger(__name__)

TG_PREVIEW_URL = "https://t.me/s/{channel}"


class TelegramChannelScraper(BaseScraper):
    """Scrapes public Telegram channel posts via web preview."""

    def __init__(self, channel_username: str, timeout: int = 30) -> None:
        self.channel = channel_username.lstrip("@").strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
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

        all_posts: list[RawArticle] = []
        seen_links: set[str] = set()

        # Fetch the channel page (gets the most recent ~20 posts)
        # Then paginate backwards via "before" parameter
        before_id = None
        consecutive_old = 0
        max_pages = 50  # safety limit

        for page in range(max_pages):
            posts, oldest_id = self._fetch_page(before_id)

            if not posts:
                break

            in_range = 0
            too_old = 0

            for post in posts:
                if post.link in seen_links:
                    continue
                seen_links.add(post.link)

                if post.published_at:
                    pub = self._ensure_tz(post.published_at)
                    if pub > until_aware:
                        continue
                    if pub < since_aware:
                        too_old += 1
                        continue

                all_posts.append(post)
                in_range += 1

            if too_old > 0 and in_range == 0:
                consecutive_old += 1
            else:
                consecutive_old = 0

            if consecutive_old >= 2:
                break

            if oldest_id:
                before_id = oldest_id
            else:
                break

            time.sleep(0.5)

        logger.info(
            "TG @%s: fetched %d posts in range %s – %s",
            self.channel, len(all_posts), since_aware.date(), until_aware.date(),
        )
        return all_posts

    def _fetch_page(self, before_id: int | None = None) -> tuple[list[RawArticle], int | None]:
        """Fetch one page of channel posts. Returns (posts, oldest_message_id)."""
        url = TG_PREVIEW_URL.format(channel=self.channel)
        params = {}
        if before_id:
            params["before"] = before_id

        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 404:
                    logger.error("TG channel @%s not found (404)", self.channel)
                    return [], None
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                logger.error("TG @%s page fetch failed: %s", self.channel, exc)
                return [], None

        soup = BeautifulSoup(resp.text, "html.parser")
        posts: list[RawArticle] = []
        oldest_id = None

        # Find message widgets
        message_els = soup.select("div.tgme_widget_message_wrap")
        if not message_els:
            message_els = soup.select("div.tgme_widget_message")

        for msg_wrap in message_els:
            msg_el = msg_wrap.select_one("div.tgme_widget_message") or msg_wrap
            post = self._parse_message(msg_el)
            if post:
                posts.append(post)

                # Track oldest ID for pagination
                msg_id = self._extract_msg_id(post.link)
                if msg_id is not None:
                    if oldest_id is None or msg_id < oldest_id:
                        oldest_id = msg_id

        return posts, oldest_id

    def _parse_message(self, el) -> RawArticle | None:
        """Parse a single Telegram message element."""
        # Get message link
        data_post = el.get("data-post", "")
        if not data_post:
            link_el = el.select_one("a.tgme_widget_message_date")
            if link_el:
                href = link_el.get("href", "")
                data_post = href.replace("https://t.me/", "")
            else:
                return None

        link = f"https://t.me/{data_post}"

        # Get text content
        text_el = el.select_one("div.tgme_widget_message_text")
        raw_text = text_el.get_text(separator="\n", strip=True) if text_el else ""

        # Get datetime
        time_el = el.select_one("time")
        pub_dt = None
        if time_el:
            dt_str = time_el.get("datetime", "")
            if dt_str:
                pub_dt = self._parse_iso(dt_str)

        # If no text, skip (media-only posts)
        if not raw_text:
            return None

        # Title: first line or first 100 chars
        lines = raw_text.split("\n")
        title = lines[0][:150] if lines else raw_text[:150]

        # Detect forwards (reposts)
        fwd_el = el.select_one("a.tgme_widget_message_forwarded_from_name")
        tags = [f"tg:@{self.channel}"]
        if fwd_el:
            fwd_name = fwd_el.get_text(strip=True)
            fwd_href = fwd_el.get("href", "")
            if fwd_href:
                # Extract channel from forward link
                fwd_match = re.search(r"t\.me/(\w+)", fwd_href)
                if fwd_match:
                    tags.append(f"repost:@{fwd_match.group(1)}")
            if fwd_name:
                tags.append(f"fwd:{fwd_name}")
                title = f"[Репост: {fwd_name}] {title}"

        return RawArticle(
            source=f"tg_{self.channel}",
            title=title,
            link=link,
            published_at=pub_dt,
            raw_text=raw_text,
            native_tags=tags,
        )

    @staticmethod
    def _extract_msg_id(link: str) -> int | None:
        m = re.search(r"/(\d+)$", link)
        return int(m.group(1)) if m else None

    @staticmethod
    def _ensure_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _parse_iso(s: str) -> datetime | None:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None


def test_channel(username: str) -> dict:
    """Test-parse a channel: fetch latest posts and return summary.

    Returns {"ok": bool, "channel": str, "title": str, "post_count": int,
             "latest_post": str, "error": str}.
    """
    channel = username.lstrip("@").strip()

    # Extract username from full URL if needed
    if "/" in channel:
        m = re.search(r"t\.me/(\w+)", channel)
        if m:
            channel = m.group(1)
        else:
            return {"ok": False, "channel": channel, "error": "Неверный формат ссылки"}

    try:
        scraper = TelegramChannelScraper(channel)
        now = datetime.now(timezone.utc)
        since = now - datetime.timedelta(days=7) if hasattr(datetime, 'timedelta') else now
        # Use timedelta directly
        from datetime import timedelta
        since = now - timedelta(days=7)
        posts = scraper.fetch_articles(since=since, until=now)

        # Try to get channel title from the page
        resp = scraper.session.get(
            TG_PREVIEW_URL.format(channel=channel),
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        title_el = soup.select_one("div.tgme_channel_info_header_title span")
        title = title_el.get_text(strip=True) if title_el else channel

        return {
            "ok": True,
            "channel": channel,
            "title": title,
            "post_count": len(posts),
            "latest_post": posts[0].title[:100] if posts else "",
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "channel": channel,
            "title": "",
            "post_count": 0,
            "latest_post": "",
            "error": str(exc)[:200],
        }
