"""All 17 Russian news source scrapers.

RSS-based sources use RssScraper, others use dedicated HTML scrapers.
No proxy — this runs directly on Russian VPS.
"""

from __future__ import annotations

from ru_collector.scrapers.rss_scraper import RssScraper
from ru_collector.scrapers.tass import TassScraper
from ru_collector.scrapers.news_html import IzvestiaScraper, GazetaScraper, EgScraper


# ---- RSS-based sources ----

class RiaScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="ria",
            feed_urls=["https://ria.ru/export/rss2/archive/index.xml"],
            fetch_full_page=True,
            full_text_selector="div.article__body, div.article__text",
        )


class InterfaxScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="interfax",
            feed_urls=["https://www.interfax.ru/rss.asp"],
            fetch_full_page=True,
            full_text_selector="article[itemprop='articleBody'], div.textMT, div.articleBody",
        )


class KommersantScraper(RssScraper):
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


class ForbesScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="forbes",
            feed_urls=["https://www.forbes.ru/newrss.xml"],
            fetch_full_page=True,
            full_text_selector="div.article-body, div.body-container__content",
        )


class VedomostiScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="vedomosti",
            feed_urls=["https://www.vedomosti.ru/rss/news"],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article-boxes-list",
        )


class RbcScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="rbc",
            feed_urls=["https://rssexport.rbc.ru/rbcnews/news/30/full.rss"],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article__text__overview",
        )


class RgScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="rg",
            feed_urls=["https://rg.ru/xml/index.xml"],
            fetch_full_page=True,
            full_text_selector=(
                "div.PageArticleContent_text, div.PageArticleContent_article, "
                "div.article-body, div.b-material-wrapper__text, "
                "div[itemprop='articleBody'], div.article__text"
            ),
        )


class NgScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="ng",
            feed_urls=["https://www.ng.ru/rss/"],
            fetch_full_page=True,
            full_text_selector=(
                "div.detail_text, div.article_text, div.content-text, "
                "div[itemprop='articleBody'], div.b-text, "
                "div.news-text, article.article-body"
            ),
        )


class KpScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="kp",
            feed_urls=["https://www.kp.ru/rss/allsections.xml"],
            fetch_full_page=True,
            full_text_selector=(
                "div.js-mediator-article, div[itemprop='articleBody'], "
                "div.styled-text, div.article-content, "
                "div.text-content, div.post__text"
            ),
        )


class MkScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="mk",
            feed_urls=["https://www.mk.ru/rss/index.xml"],
            fetch_full_page=True,
            full_text_selector="div.article__body, div.content__main__text",
        )


class AifScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="aif",
            feed_urls=["https://aif.ru/rss/all.php"],
            fetch_full_page=True,
            full_text_selector="div.article_text, div.article-content",
        )


class RtScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="rt",
            feed_urls=["https://russian.rt.com/rss"],
            fetch_full_page=True,
            full_text_selector="div.article__text, div.article-text, div.text-article",
        )


class LentaScraper(RssScraper):
    def __init__(self) -> None:
        super().__init__(
            source_name="lenta",
            feed_urls=["https://lenta.ru/rss"],
            fetch_full_page=True,
            full_text_selector="div.topic-body__content, div.js-topic__text",
        )


# ---- Source registry ----

ALL_SOURCES: dict[str, type] = {
    "tass": TassScraper,
    "ria": RiaScraper,
    "interfax": InterfaxScraper,
    "kommersant": KommersantScraper,
    "forbes": ForbesScraper,
    "vedomosti": VedomostiScraper,
    "rbc": RbcScraper,
    "izvestia": IzvestiaScraper,
    "rg": RgScraper,
    "ng": NgScraper,
    "kp": KpScraper,
    "mk": MkScraper,
    "aif": AifScraper,
    "gazeta": GazetaScraper,
    "rt": RtScraper,
    "lenta": LentaScraper,
    "eg": EgScraper,
}
