"""Russian news source scrapers — 17 major outlets.

Each class is a thin wrapper around ``RssScraper`` with
source-specific feed URLs and CSS selectors for full-page
article text extraction.

TASS uses a dedicated scraper (src/scrapers/tass.py).
"""

from __future__ import annotations

from src.scrapers.rss_scraper import RssScraper
from src.scrapers.tass import TassScraper


# ------------------------------------------------------------------ РИА Новости
class RiaScraper(RssScraper):
    """РИА Новости — федеральное информационное агентство."""

    def __init__(self) -> None:
        super().__init__(
            source_name="ria",
            feed_urls=[
                "https://ria.ru/export/rss2/archive/index.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__body, div.article__text",
        )


# ------------------------------------------------------------------ Интерфакс
class InterfaxScraper(RssScraper):
    """Интерфакс — независимое информационное агентство."""

    def __init__(self) -> None:
        super().__init__(
            source_name="interfax",
            feed_urls=[
                "https://www.interfax.ru/rss.asp",
            ],
            fetch_full_page=True,
            full_text_selector="article[itemprop='articleBody'], div.textMT, div.articleBody",
        )


# ------------------------------------------------------------------ Коммерсант
class KommersantScraper(RssScraper):
    """Коммерсантъ — деловое издание."""

    def __init__(self) -> None:
        super().__init__(
            source_name="kommersant",
            feed_urls=[
                "https://www.kommersant.ru/RSS/news.xml",
                "https://www.kommersant.ru/RSS/corp.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article_text_wrapper",
        )


# ------------------------------------------------------------------ Forbes Россия
class ForbesScraper(RssScraper):
    """Forbes Россия — бизнес, финансы, инвестиции."""

    def __init__(self) -> None:
        super().__init__(
            source_name="forbes",
            feed_urls=[
                "https://www.forbes.ru/newrss.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article-body, div.body-container__content",
        )


# ------------------------------------------------------------------ Ведомости
class VedomostiScraper(RssScraper):
    """Ведомости — деловая ежедневная газета."""

    def __init__(self) -> None:
        super().__init__(
            source_name="vedomosti",
            feed_urls=[
                "https://www.vedomosti.ru/rss/news",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article-boxes-list",
        )


# ------------------------------------------------------------------ РБК
class RbcScraper(RssScraper):
    """РБК — новости, финансы, аналитика."""

    def __init__(self) -> None:
        super().__init__(
            source_name="rbc",
            feed_urls=[
                "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article__text__overview",
        )


# ------------------------------------------------------------------ Известия
class IzvestiaScraper(RssScraper):
    """Известия — федеральная ежедневная газета.

    iz.ru changed their RSS structure multiple times.
    Try several known RSS paths.
    """

    def __init__(self) -> None:
        super().__init__(
            source_name="izvestia",
            feed_urls=[
                "https://iz.ru/xml/rss/all.xml",
                "https://iz.ru/feed",
                "https://iz.ru/rss",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.article__text, div.text-article, "
                "div.article_page__left__article__text, "
                "div[itemprop='articleBody'], div.article-body"
            ),
        )


# ------------------------------------------------------------------ Российская газета
class RgScraper(RssScraper):
    """Российская газета — официальное издание правительства РФ.

    RG has multiple page templates; need broad selector coverage.
    """

    def __init__(self) -> None:
        super().__init__(
            source_name="rg",
            feed_urls=[
                "https://rg.ru/xml/index.xml",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.PageArticleContent_text, div.PageArticleContent_article, "
                "div.article-body, div.b-material-wrapper__text, "
                "div[itemprop='articleBody'], div.article__text"
            ),
        )


# ------------------------------------------------------------------ Независимая газета
class NgScraper(RssScraper):
    """Независимая газета — общественно-политическое издание."""

    def __init__(self) -> None:
        super().__init__(
            source_name="ng",
            feed_urls=[
                "https://www.ng.ru/rss/",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.detail_text, div.article_text, div.content-text, "
                "div[itemprop='articleBody'], div.b-text, "
                "div.news-text, article.article-body"
            ),
        )


# ------------------------------------------------------------------ Комсомольская правда
class KpScraper(RssScraper):
    """Комсомольская правда — массовое ежедневное издание.

    KP uses 'Mediator' content platform with dynamic loading.
    """

    def __init__(self) -> None:
        super().__init__(
            source_name="kp",
            feed_urls=[
                "https://www.kp.ru/rss/allsections.xml",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.js-mediator-article, div[itemprop='articleBody'], "
                "div.styled-text, div.article-content, "
                "div.text-content, div.post__text"
            ),
        )


# ------------------------------------------------------------------ Московский комсомолец
class MkScraper(RssScraper):
    """Московский комсомолец — ежедневная газета."""

    def __init__(self) -> None:
        super().__init__(
            source_name="mk",
            feed_urls=[
                "https://www.mk.ru/rss/index.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__body, div.content__main__text",
        )


# ------------------------------------------------------------------ Аргументы и факты
class AifScraper(RssScraper):
    """Аргументы и факты — еженедельная газета."""

    def __init__(self) -> None:
        super().__init__(
            source_name="aif",
            feed_urls=[
                "https://aif.ru/rss/all.php",
            ],
            fetch_full_page=True,
            full_text_selector="div.article_text, div.article-content",
        )


# ------------------------------------------------------------------ Gazeta.ru
class GazetaScraper(RssScraper):
    """Gazeta.ru — общественно-политическое интернет-издание.

    gazeta.ru changed RSS paths; try several known URLs.
    """

    def __init__(self) -> None:
        super().__init__(
            source_name="gazeta",
            feed_urls=[
                "https://www.gazeta.ru/export/rss/lenta.xml",
                "https://www.gazeta.ru/export/rss/first.xml",
                "https://www.gazeta.ru/rss/all.xml",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.article_text_body, div.maintext, "
                "div[itemprop='articleBody'], div.b-text"
            ),
        )


# ------------------------------------------------------------------ RT на русском
class RtScraper(RssScraper):
    """RT (Russia Today) — международное СМИ на русском."""

    def __init__(self) -> None:
        super().__init__(
            source_name="rt",
            feed_urls=[
                "https://russian.rt.com/rss",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article-text, div.text-article",
        )


# ------------------------------------------------------------------ Lenta.ru
class LentaScraper(RssScraper):
    """Lenta.ru — одно из крупнейших российских интернет-изданий."""

    def __init__(self) -> None:
        super().__init__(
            source_name="lenta",
            feed_urls=[
                "https://lenta.ru/rss",
            ],
            fetch_full_page=True,
            full_text_selector="div.topic-body__content, div.js-topic__text",
        )


# ------------------------------------------------------------------ Экспресс газета
class EgScraper(RssScraper):
    """Экспресс газета — развлекательное издание.

    eg.ru RSS might be at different paths.
    """

    def __init__(self) -> None:
        super().__init__(
            source_name="eg",
            feed_urls=[
                "https://www.eg.ru/rss/",
                "https://eg.ru/feed/",
                "https://eg.ru/rss",
            ],
            fetch_full_page=True,
            full_text_selector=(
                "div.article__text, div.post-content, "
                "div.entry-content, div[itemprop='articleBody']"
            ),
        )


# ------------------------------------------------------------------
# Registry helper: all news source configs in one place
# ------------------------------------------------------------------

NEWS_SOURCES = [
    {
        "name": "tass",
        "scraper_class": TassScraper,
        "description": "ТАСС — государственное информационное агентство",
        "icon": "🏛️",
    },
    {
        "name": "ria",
        "scraper_class": RiaScraper,
        "description": "РИА Новости — федеральное информационное агентство",
        "icon": "📡",
    },
    {
        "name": "interfax",
        "scraper_class": InterfaxScraper,
        "description": "Интерфакс — независимое информационное агентство",
        "icon": "📰",
    },
    {
        "name": "kommersant",
        "scraper_class": KommersantScraper,
        "description": "Коммерсантъ — деловое издание",
        "icon": "💰",
    },
    {
        "name": "forbes",
        "scraper_class": ForbesScraper,
        "description": "Forbes Россия — бизнес и финансы",
        "icon": "📊",
    },
    {
        "name": "vedomosti",
        "scraper_class": VedomostiScraper,
        "description": "Ведомости — деловая газета",
        "icon": "📋",
    },
    {
        "name": "rbc",
        "scraper_class": RbcScraper,
        "description": "РБК — новости и аналитика",
        "icon": "📈",
    },
    {
        "name": "izvestia",
        "scraper_class": IzvestiaScraper,
        "description": "Известия — федеральная газета",
        "icon": "🗞️",
    },
    {
        "name": "rg",
        "scraper_class": RgScraper,
        "description": "Российская газета — официальное издание",
        "icon": "🇷🇺",
    },
    {
        "name": "ng",
        "scraper_class": NgScraper,
        "description": "Независимая газета — общественно-политическое издание",
        "icon": "📰",
    },
    {
        "name": "kp",
        "scraper_class": KpScraper,
        "description": "Комсомольская правда — ежедневное издание",
        "icon": "⭐",
    },
    {
        "name": "mk",
        "scraper_class": MkScraper,
        "description": "Московский комсомолец — ежедневная газета",
        "icon": "📰",
    },
    {
        "name": "aif",
        "scraper_class": AifScraper,
        "description": "Аргументы и факты — еженедельная газета",
        "icon": "📰",
    },
    {
        "name": "gazeta",
        "scraper_class": GazetaScraper,
        "description": "Gazeta.ru — интернет-издание",
        "icon": "🌐",
    },
    {
        "name": "rt",
        "scraper_class": RtScraper,
        "description": "RT на русском — международное СМИ",
        "icon": "📺",
    },
    {
        "name": "lenta",
        "scraper_class": LentaScraper,
        "description": "Lenta.ru — интернет-издание",
        "icon": "📰",
    },
    {
        "name": "eg",
        "scraper_class": EgScraper,
        "description": "Экспресс газета — развлекательное издание",
        "icon": "🎭",
    },
]
