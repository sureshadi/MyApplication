"""Application settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feed:
    source: str
    url: str


# Public RSS feeds from major financial news outlets.
DEFAULT_FEEDS: tuple[Feed, ...] = (
    Feed("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
    Feed("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    Feed("Wall Street Journal", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
    Feed("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    Feed("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    Feed("Financial Times", "https://www.ft.com/markets?format=rss"),
)

# Per-ticker headlines. {symbol} is replaced with the ticker.
TICKER_NEWS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


@dataclass(frozen=True)
class Settings:
    feeds: tuple[Feed, ...] = DEFAULT_FEEDS
    ticker_news_url: str = TICKER_NEWS_URL
    finnhub_api_key: str | None = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY") or None)
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300")))
    http_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "10")))
    max_front_page_items: int = 60


def get_settings() -> Settings:
    return Settings()
