"""Application settings, read from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feed:
    source: str
    url: str
    short: str = ""  # short label for the sidebar, e.g. "WSJ"

    @property
    def label(self) -> str:
        return self.short or self.source

    @property
    def slug(self) -> str:
        """URL-safe id used in ?source=, e.g. "wsj"."""
        return re.sub(r"[^a-z0-9]+", "-", self.label.lower()).strip("-")


# Public RSS feeds from major financial news outlets shown on the front page.
# Yahoo Finance and MarketWatch are left out for now.
DEFAULT_FEEDS: tuple[Feed, ...] = (
    Feed("Wall Street Journal", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "WSJ"),
    Feed("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT"),
    Feed("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "CNBC"),
    Feed("Financial Times", "https://www.ft.com/markets?format=rss", "FT"),
)

@dataclass(frozen=True)
class Topic:
    """A themed news tab with its own page, e.g. Technology at /technology."""

    slug: str
    title: str
    feeds: tuple[Feed, ...]


# Themed news tabs shown after "Financial news" in the top tab bar, in this order.
DEFAULT_TOPICS: tuple[Topic, ...] = (
    Topic(
        "technology",
        "Technology",
        (
            Feed("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "NYT"),
            Feed("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910", "CNBC"),
        ),
    ),
    Topic(
        "health",
        "Health",
        (
            Feed("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "NYT"),
            Feed("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000108", "CNBC"),
        ),
    ),
)

# Per-ticker headlines. {symbol} is replaced with the ticker.
TICKER_NEWS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


DEFAULT_WATCHLIST = "AAPL,META,NVDA,AMAT,AVGO,LLY,GOOGL,MSFT"


def _watchlist_from_env() -> tuple[str, ...]:
    raw = os.getenv("WATCHLIST", DEFAULT_WATCHLIST)
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


@dataclass(frozen=True)
class Settings:
    feeds: tuple[Feed, ...] = DEFAULT_FEEDS
    topics: tuple[Topic, ...] = DEFAULT_TOPICS
    # Headlines on a themed tab (Technology, Health), mixed evenly across its feeds.
    max_items_per_topic: int = 30
    ticker_news_url: str = TICKER_NEWS_URL
    finnhub_api_key: str | None = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY") or None)
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300")))
    http_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "10")))
    max_front_page_items: int = 60
    # How many headlines to show when the reader picks a single source in the sidebar.
    max_items_single_source: int = 40
    # Tickers shown in the top bar by default. Visitors can add or remove their own.
    watchlist: tuple[str, ...] = field(default_factory=_watchlist_from_env)
    max_quote_symbols: int = 25
    # Keeps a balanced mix: no single outlet can fill more than this many front-page slots.
    max_items_per_source: int = field(default_factory=lambda: int(os.getenv("MAX_ITEMS_PER_SOURCE", "12")))
    # Market research (My Portfolio). SEC asks automated clients to identify themselves with a
    # name and contact email, e.g. "Jane Doe jane@example.com".
    sec_user_agent: str = field(
        default_factory=lambda: os.getenv("SEC_USER_AGENT") or "MarketHeadlines research agent admin@market-headlines.example"
    )
    # Filings change at most a few times a quarter, so analyses are kept for hours, not minutes.
    research_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("RESEARCH_TTL_SECONDS", "21600")))
    # Headlines shown in the side panel when a ticker is clicked on My Portfolio.
    panel_news_items: int = 3


def get_settings() -> Settings:
    return Settings()
