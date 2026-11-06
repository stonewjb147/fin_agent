"""News overlay: point-in-time filtered, bounded, and always explainable."""

from finagent.news.overlay import (
    DEFAULT_MAX_ABS,
    DEFAULT_WEIGHT,
    NewsItem,
    NewsLoad,
    apply_news_overlay,
    load_news,
    load_news_map,
    news_scores,
)

__all__ = [
    "DEFAULT_MAX_ABS",
    "DEFAULT_WEIGHT",
    "NewsItem",
    "NewsLoad",
    "apply_news_overlay",
    "load_news",
    "load_news_map",
    "news_scores",
]
