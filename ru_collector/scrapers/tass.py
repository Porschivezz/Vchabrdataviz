"""ТАСС (tass.ru) — advanced scraper for Russian VPS.

Architecture notes (from site analysis):
- Discovery: RSS feeds work perfectly (/rss/v2.xml + section feeds)
- Article pages: Next.js/React SPA with obfuscated CSS classes
  (Text-module_root__..., text-block, etc.)
- WAF: Servicepipe/Qrator with TLS fingerprinting + JS challenge + ASN blocking
- Best text sources (in priority order):
  1. __NEXT_DATA__ JSON embedded in page (contains full article text)
  2. JSON-LD structured data (articleBody)
  3. Wildcard CSS selectors for obfuscated class names
  4. AMP page versions (/amp/ prefix)
  5. RSS description/content as fallback
  6. og:description meta tag as last resort
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, Tag

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

# Stop-words to filter out non-article paragraphs
_STOP_PHRASES = re.compile(
    r"(читайте также|подписывайтесь|подробнее на|все новости|"
    r"теги:|поделиться|источник:|фото:|©|tass\.ru/rss|"
    r"telegram|дзен|вконтакте|одноклассники)",
    re.IGNORECASE,
)

# CSS class fragments that indicate ad/promo/nav containers
_JUNK_CLASS_PATTERNS = re.compile(
    r"(caption|promo|advert|related|banner|share|social|subscribe|"
    r"recommend|footer|header|nav|sidebar|widget|cookie|popup|modal|"
    r"Gallery|Photo-module|Sticky|Authors-module|Tags-module)",
    re.IGNORECASE,
)


def _is_article_url(href: str) -> bool:
    if not href.startswith(TASS_HOME):
        return False
    path = href[len(TASS_HOME):]
    if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    return bool(re.match(r"^/[\w-]+(/[\w-]+)?/\d+$", path))


def _article_id_from_url(url: str) -> str:
    """Extract numeric article ID from URL like https://tass.ru/section/12345."""
    m = re.search(r"/(\d+)$", url)
    return m.group(1) if m else ""


def _clean_paragraphs(paragraphs: list[str]) -> list[str]:
    """Filter out junk paragraphs by stop-phrases."""
    result = []
    for p in paragraphs:
        if len(p) < 15:
            continue
        if _STOP_PHRASES.search(p):
            continue
        result.append(p)
    return result


def _is_junk_container(el: Tag) -> bool:
    """Check if element's class suggests it's not article content."""
    cls = " ".join(el.get("class", []))
    return bool(_JUNK_CLASS_PATTERNS.search(cls))


class TassScraper(BaseScraper):
    """ТАСС — multi-strategy text extraction."""

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

        # Discover from RSS (always works)
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
    # RSS Discovery
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
                link = self._extract_rss_link(item)
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

                # Extract RSS text — this is our fallback if page scraping fails
                rss_text = self._extract_rss_text(item)

                stubs.append({
                    "link": link,
                    "title": title,
                    "published_at": pub_dt,
                    "rss_text": rss_text,
                })

            time.sleep(0.2)

        return stubs

    def _extract_rss_link(self, item) -> str:
        link_el = item.find("link")
        if link_el:
            link = (link_el.get_text(strip=True)
                    or (link_el.string and str(link_el.string).strip())
                    or "")
            if link:
                return link
        if link_el and link_el.next_sibling:
            sib = str(link_el.next_sibling).strip()
            if sib.startswith("http"):
                return sib
        guid_el = item.find("guid")
        if guid_el:
            g = guid_el.get_text(strip=True)
            if g.startswith("http"):
                return g
        return ""

    def _extract_rss_text(self, item) -> str:
        """Extract maximum text from RSS item fields."""
        best = ""

        # content:encoded often has full HTML
        for tag_name in ("content:encoded", "content", "description", "summary"):
            el = item.find(tag_name)
            if not el:
                continue
            raw = el.get_text(strip=True) if el.string is None else el.string.strip()
            if not raw:
                continue
            # If HTML, parse out text
            if "<" in raw and ">" in raw:
                text_soup = BeautifulSoup(raw, "html.parser")
                text = text_soup.get_text(separator="\n", strip=True)
            else:
                text = raw
            if len(text) > len(best):
                best = text

        return best

    # ------------------------------------------------------------------
    # HTML Listing Fallback
    # ------------------------------------------------------------------

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
                stubs.append({
                    "link": href,
                    "title": title[:200],
                    "published_at": None,
                    "rss_text": "",
                })

            time.sleep(0.3)

        return stubs

    # ------------------------------------------------------------------
    # Article Parsing — multi-strategy text extraction
    # ------------------------------------------------------------------

    def _parse_article(self, stub: dict, since: datetime, until: datetime) -> RawArticle | None:
        url = stub["link"]
        rss_text = stub.get("rss_text", "")

        # Try fetching article page
        page_text, page_title, page_lead, pub_dt_page, tags = self._fetch_article_page(url)

        # Try AMP version if main page gave no text
        if len(page_text) < 200:
            amp_text = self._fetch_amp_page(url)
            if len(amp_text) > len(page_text):
                page_text = amp_text
                logger.debug("TASS: AMP gave better text for %s (%d chars)", url, len(amp_text))

        # Build final text: best of page_text vs rss_text
        body_text = page_text if len(page_text) > len(rss_text) else rss_text

        # Combine lead + body
        lead = page_lead
        if lead and lead not in body_text:
            body_text = f"{lead}\n\n{body_text}" if body_text else lead

        # Title
        title = stub.get("title", "") or page_title

        # Date
        pub_dt = stub.get("published_at") or pub_dt_page

        if pub_dt:
            pub_aware = _ensure_tz(pub_dt)
            if pub_aware > until or pub_aware < since:
                return None

        if not title and not body_text:
            return None

        # Section tag from URL
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

    def _fetch_article_page(self, url: str) -> tuple[str, str, str, datetime | None, list[str]]:
        """Fetch article page and try all extraction strategies.

        Returns (body_text, title, lead, published_at, tags).
        """
        empty = ("", "", "", None, [])

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("TASS article %s failed: %s", url, exc)
            return empty

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # --- Title ---
        title = ""
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
        for sel in (
            "div.news-header__lead",
            "div[class*='lead']",
            "p.lead",
            "div[class*='Lead']",
        ):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True) and not _is_junk_container(el):
                lead = el.get_text(strip=True)
                break

        # --- Strategy 1: __NEXT_DATA__ JSON (best source for Next.js sites) ---
        body_text = self._extract_from_next_data(soup)
        if body_text and len(body_text) > 200:
            logger.debug("TASS: __NEXT_DATA__ extraction success for %s (%d chars)", url, len(body_text))
        else:
            # --- Strategy 2: JSON-LD articleBody ---
            body_text = self._extract_from_jsonld(soup)
            if body_text and len(body_text) > 200:
                logger.debug("TASS: JSON-LD extraction success for %s (%d chars)", url, len(body_text))

        if not body_text or len(body_text) < 200:
            # --- Strategy 3: Wildcard CSS selectors for obfuscated classes ---
            css_text = self._extract_from_css_wildcards(soup)
            if len(css_text) > len(body_text):
                body_text = css_text
                logger.debug("TASS: CSS wildcard extraction for %s (%d chars)", url, len(body_text))

        if not body_text or len(body_text) < 200:
            # --- Strategy 4: Classic <p>-in-container extraction ---
            classic_text = self._extract_classic(soup)
            if len(classic_text) > len(body_text):
                body_text = classic_text

        if not body_text or len(body_text) < 100:
            # --- Strategy 5: og:description fallback ---
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc:
                desc = og_desc.get("content", "")
                if desc and len(desc) > len(body_text):
                    body_text = desc

        # --- Date ---
        pub_dt = self._extract_date(soup)

        # --- Tags ---
        tags: list[str] = []
        for a in soup.select("a[href*='/tag/'], div.tags a, a[class*='Tag']"):
            t = a.get_text(strip=True)
            if t and len(t) < 100:
                tags.append(t)

        return (body_text, title, lead, pub_dt, tags)

    # ------------------------------------------------------------------
    # Text extraction strategies
    # ------------------------------------------------------------------

    def _extract_from_next_data(self, soup: BeautifulSoup) -> str:
        """Strategy 1: Extract article text from __NEXT_DATA__ JSON.

        Next.js embeds page data as JSON in <script id="__NEXT_DATA__">.
        The article text is typically in props.pageProps.article.text or similar.
        """
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return ""

        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            return ""

        # Walk the JSON tree looking for article text fields
        return self._find_article_text_in_json(data)

    def _find_article_text_in_json(self, obj, depth: int = 0) -> str:
        """Recursively search JSON for article text content."""
        if depth > 15:
            return ""

        best = ""

        if isinstance(obj, dict):
            # Direct text fields
            for key in ("text", "articleBody", "body", "content", "fullText",
                        "article_text", "newsText", "richText"):
                val = obj.get(key)
                if isinstance(val, str) and len(val) > len(best):
                    # Could be HTML — strip tags
                    if "<" in val and ">" in val:
                        text_soup = BeautifulSoup(val, "html.parser")
                        clean = text_soup.get_text(separator="\n", strip=True)
                    else:
                        clean = val.strip()
                    if len(clean) > len(best):
                        best = clean

            # Check for blocks/items arrays (TASS often stores text as blocks)
            for key in ("blocks", "items", "textBlocks", "paragraphs", "nodes"):
                val = obj.get(key)
                if isinstance(val, list):
                    parts = []
                    for block in val:
                        if isinstance(block, dict):
                            # Each block may have 'text', 'value', 'content', 'data'
                            for bk in ("text", "value", "content", "data"):
                                bv = block.get(bk)
                                if isinstance(bv, str) and len(bv) > 15:
                                    if "<" in bv and ">" in bv:
                                        bsoup = BeautifulSoup(bv, "html.parser")
                                        bv = bsoup.get_text(separator="\n", strip=True)
                                    parts.append(bv.strip())
                                    break
                            # Block might have nested children
                            for bk in ("children", "content", "blocks"):
                                nested = block.get(bk)
                                if isinstance(nested, list):
                                    for child in nested:
                                        if isinstance(child, dict):
                                            for ck in ("text", "value", "content"):
                                                cv = child.get(ck)
                                                if isinstance(cv, str) and len(cv) > 10:
                                                    parts.append(cv.strip())
                                                    break
                                        elif isinstance(child, str) and len(child) > 10:
                                            parts.append(child.strip())
                        elif isinstance(block, str) and len(block) > 15:
                            parts.append(block.strip())
                    joined = "\n\n".join(_clean_paragraphs(parts))
                    if len(joined) > len(best):
                        best = joined

            # Recurse into all dict values
            for key, val in obj.items():
                if key in ("text", "articleBody", "body", "content", "blocks", "items"):
                    continue  # already handled
                found = self._find_article_text_in_json(val, depth + 1)
                if len(found) > len(best):
                    best = found

        elif isinstance(obj, list):
            for item in obj:
                found = self._find_article_text_in_json(item, depth + 1)
                if len(found) > len(best):
                    best = found

        return best

    def _extract_from_jsonld(self, soup: BeautifulSoup) -> str:
        """Strategy 2: Extract articleBody from JSON-LD structured data."""
        best = ""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for key in ("articleBody", "text", "description"):
                        val = item.get(key, "")
                        if isinstance(val, str) and len(val) > len(best):
                            best = val
            except (json.JSONDecodeError, KeyError):
                continue
        return best

    def _extract_from_css_wildcards(self, soup: BeautifulSoup) -> str:
        """Strategy 3: Use wildcard CSS selectors for obfuscated TASS classes.

        TASS uses classes like Text-module_root__..., text-block, NewsBody_... etc.
        """
        # Selectors ordered from most specific to least
        wildcard_selectors = [
            "div[class*='text-content']",
            "div[class*='Text-module']",
            "div[class*='text-block']",
            "div[class*='TextBlock']",
            "div[class*='NewsBody']",
            "div[class*='news-body']",
            "div[class*='ArticleBody']",
            "div[class*='article-body']",
            "div[class*='Article_text']",
            "div[class*='Content_root']",
            "div[class*='PageContent']",
            "main[class*='content']",
            "article[class*='Article']",
            "article",
        ]

        best_text = ""

        for sel in wildcard_selectors:
            containers = soup.select(sel)
            for container in containers:
                if _is_junk_container(container):
                    continue

                # Gather all text nodes from p, div, span within the container
                paragraphs = []

                # First try <p> tags
                for p in container.find_all("p", recursive=True):
                    if p.parent and _is_junk_container(p.parent):
                        continue
                    text = p.get_text(strip=True)
                    if text and len(text) > 20:
                        paragraphs.append(text)

                # If no <p> tags found, try direct text extraction
                # (TASS sometimes uses divs/spans instead of p)
                if not paragraphs:
                    for child in container.find_all(["div", "span"], recursive=True):
                        if _is_junk_container(child):
                            continue
                        # Only leaf nodes (no nested divs with text)
                        if child.find(["div", "span", "p"]):
                            continue
                        text = child.get_text(strip=True)
                        if text and len(text) > 30:
                            paragraphs.append(text)

                cleaned = _clean_paragraphs(paragraphs)
                result = "\n\n".join(cleaned)

                if len(result) > len(best_text):
                    best_text = result

            if len(best_text) > 300:
                break  # Good enough, stop searching

        return best_text

    def _extract_classic(self, soup: BeautifulSoup) -> str:
        """Strategy 4: Classic container + <p> tag extraction."""
        for container_sel in (
            "div.text-content",
            "div.news-body",
            "div[class*='NewsBody']",
            "article",
            "main",
            "div[class*='text']",
        ):
            container = soup.select_one(container_sel)
            if not container or _is_junk_container(container):
                continue

            paragraphs = []
            for p in container.find_all("p"):
                if p.parent and _is_junk_container(p.parent):
                    continue
                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    paragraphs.append(text)

            cleaned = _clean_paragraphs(paragraphs)
            if cleaned:
                return "\n\n".join(cleaned)

        return ""

    def _fetch_amp_page(self, url: str) -> str:
        """Try fetching AMP version of the article for simpler HTML."""
        # Convert https://tass.ru/section/12345 to https://tass.ru/amp/section/12345
        amp_url = url.replace("tass.ru/", "tass.ru/amp/", 1)

        try:
            resp = self.session.get(amp_url, timeout=self.timeout)
            if resp.status_code != 200:
                return ""
        except requests.RequestException:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # AMP pages typically have cleaner, flatter HTML
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 20:
                paragraphs.append(text)

        cleaned = _clean_paragraphs(paragraphs)
        return "\n\n".join(cleaned)

    # ------------------------------------------------------------------
    # Date extraction
    # ------------------------------------------------------------------

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
            "time[class*='Date']",
        ):
            el = soup.select_one(sel)
            if el:
                # Try datetime attr first, then text
                dt_str = el.get("datetime", "") or el.get_text(strip=True)
                if dt_str:
                    dt = _parse_datetime(dt_str)
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

        # Try __NEXT_DATA__ for date
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                data = json.loads(script.string)
                dt = self._find_date_in_json(data)
                if dt:
                    return dt
            except json.JSONDecodeError:
                pass

        return None

    def _find_date_in_json(self, obj, depth: int = 0) -> datetime | None:
        """Search JSON tree for publication date."""
        if depth > 10:
            return None

        if isinstance(obj, dict):
            for key in ("publishedAt", "published_at", "datePublished",
                        "date", "pubDate", "created_at", "createdAt"):
                val = obj.get(key)
                if isinstance(val, str):
                    dt = _parse_datetime(val)
                    if dt:
                        return dt
                elif isinstance(val, (int, float)):
                    # Unix timestamp
                    try:
                        return datetime.fromtimestamp(val, tz=timezone.utc)
                    except (ValueError, OSError):
                        pass

            # Recurse into likely containers
            for key in ("article", "news", "data", "props", "pageProps", "result"):
                if key in obj:
                    dt = self._find_date_in_json(obj[key], depth + 1)
                    if dt:
                        return dt

        return None
