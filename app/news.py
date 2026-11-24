"""Fetch, normalize, de-duplicate and sort financial news from RSS feeds."""

from __future__ import annotations

import asyncio
import calendar
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

from .config import Feed

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; FinanceNewsApp/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
        }


def clean_text(value: str | None, max_len: int | None = None) -> str:
    """Strip HTML tags and entities, collapse whitespace, optionally truncate."""
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    text = " ".join(text.split())
    if max_len and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _parse_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def parse_feed(content: bytes | str, source: str) -> list[NewsItem]:
    """Parse raw RSS/Atom content into NewsItems. Entries without a title or link are skipped."""
    parsed = feedparser.parse(content)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title"))
        link = (entry.get("link") or "").strip()
        if not title or not link.lower().startswith(("http://", "https://")):
            continue
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                published=_parse_date(entry),
                summary=clean_text(entry.get("summary"), max_len=280),
            )
        )
    return items


def _title_key(title: str) -> str:
    return " ".join(_NON_WORD_RE.sub(" ", title.lower()).split())


def merge_news(
    groups: list[list[NewsItem]], limit: int | None = None, max_per_source: int | None = None
) -> list[NewsItem]:
    """Combine items from several feeds: drop duplicates (same link or same title), newest first.

    max_per_source keeps the newest N items from each source, so one busy feed can't crowd out the rest.
    """
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[NewsItem] = []
    for group in groups:
        for item in group:
            link_key = item.link.split("?")[0].rstrip("/").lower()
            title_key = _title_key(item.title)
            if link_key in seen_links or title_key in seen_titles:
                continue
            seen_links.add(link_key)
            seen_titles.add(title_key)
            merged.append(item)

    oldest = datetime.min.replace(tzinfo=timezone.utc)
    merged.sort(key=lambda i: i.published or oldest, reverse=True)
    if max_per_source:
        per_source: dict[str, int] = {}
        capped = []
        for item in merged:
            per_source[item.source] = per_source.get(item.source, 0) + 1
            if per_source[item.source] <= max_per_source:
                capped.append(item)
        merged = capped
    return merged[:limit] if limit else merged


async def fetch_feed(client: httpx.AsyncClient, feed: Feed) -> list[NewsItem]:
    """Fetch one feed. A failing feed returns an empty list so one outage can't break the page."""
    try:
        resp = await client.get(feed.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Feed %s failed: %s", feed.source, exc)
        return []
    return parse_feed(resp.content, feed.source)


async def fetch_all(
    client: httpx.AsyncClient,
    feeds: tuple[Feed, ...] | list[Feed],
    limit: int | None = None,
    max_per_source: int | None = None,
) -> list[NewsItem]:
    groups = await asyncio.gather(*(fetch_feed(client, f) for f in feeds))
    return merge_news(list(groups), limit=limit, max_per_source=max_per_source)


# Words that don't identify a company on their own ("Apple Inc." -> "Apple").
_COMPANY_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "lp",
    "holdings", "holding", "group", "sa", "nv", "ag", "se", "the", "class", "de",
}


def company_keywords(name: str | None) -> list[str]:
    """Distinctive words of a company name: 'Meta Platforms, Inc.' -> ['meta', 'platforms']."""
    words = re.findall(r"[a-z0-9&]+", (name or "").lower())
    return [w for w in words if w not in _COMPANY_SUFFIXES and len(w) >= 3]


def mentions_company(item: NewsItem, symbol: str, name: str | None = None) -> bool:
    """True if the headline or summary names the ticker (e.g. 'AAPL') or the company's first name word."""
    text = f"{item.title} {item.summary}"
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", text):
        return True
    keywords = company_keywords(name)
    if not keywords:
        return False
    return re.search(rf"\b{re.escape(keywords[0])}\b", text.lower()) is not None


def about_company(items: list[NewsItem], symbol: str, name: str | None, limit: int) -> list[NewsItem]:
    """Headlines that mention the company first. If there are fewer than `limit`, top up with the
    other headlines from the feed, in their original order, so the reader still gets `limit` items."""
    relevant = [i for i in items if mentions_company(i, symbol, name)]
    if len(relevant) >= limit:
        return relevant[:limit]
    rest = [i for i in items if i not in relevant]
    return relevant + rest[: limit - len(relevant)]
