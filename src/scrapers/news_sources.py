"""Russian news source scrapers — 17 major outlets.

Each class is a thin wrapper around ``RssScraper`` with
source-specific feed URLs and (optionally) a CSS selector
for full-page article text extraction.
"""

from __future__ import annotations

from src.scrapers.rss_scraper import RssScraper


# ------------------------------------------------------------------ ТАСС
class TassScraper(RssScraper):
    """ТАСС — главное государственное информационное агентство."""

    def __init__(self) -> None:
        super().__init__(
            source_name="tass",
            feed_urls=[
                "https://tass.ru/rss/v2.xml",
            ],
            fetch_full_page=True,
            full_text_selector="article.news-text, div.text-content, div.news-article__text",
        )


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
    """Известия — федеральная ежедневная газета."""

    def __init__(self) -> None:
        super().__init__(
            source_name="izvestia",
            feed_urls=[
                "https://iz.ru/xml/rss/all.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article_page__left__article__text, div.text-article",
        )


# ------------------------------------------------------------------ Российская газета
class RgScraper(RssScraper):
    """Российская газета — официальное издание правительства РФ."""

    def __init__(self) -> None:
        super().__init__(
            source_name="rg",
            feed_urls=[
                "https://rg.ru/xml/index.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article-body, div.PageArticleContent_article",
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
            full_text_selector="div.article_text, div.content-text",
        )


# ------------------------------------------------------------------ Комсомольская правда
class KpScraper(RssScraper):
    """Комсомольская правда — массовое ежедневное издание."""

    def __init__(self) -> None:
        super().__init__(
            source_name="kp",
            feed_urls=[
                "https://www.kp.ru/rss/allsections.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article-content, div.styled-text, div.js-mediator-article",
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
    """Gazeta.ru — общественно-политическое интернет-издание."""

    def __init__(self) -> None:
        super().__init__(
            source_name="gazeta",
            feed_urls=[
                "https://www.gazeta.ru/export/rss/lenta.xml",
                "https://www.gazeta.ru/export/rss/first.xml",
            ],
            fetch_full_page=True,
            full_text_selector="div.article_text_body, div.maintext",
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
    """Экспресс газета — развлекательное издание."""

    def __init__(self) -> None:
        super().__init__(
            source_name="eg",
            feed_urls=[
                "https://www.eg.ru/rss/",
            ],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.post-content, div.entry-content",
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
