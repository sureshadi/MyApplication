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


def merge_news(groups: list[list[NewsItem]], limit: int | None = None) -> list[NewsItem]:
    """Combine items from several feeds: drop duplicates (same link or same title), newest first."""
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


async def fetch_all(client: httpx.AsyncClient, feeds: tuple[Feed, ...] | list[Feed], limit: int | None = None) -> list[NewsItem]:
    groups = await asyncio.gather(*(fetch_feed(client, f) for f in feeds))
    return merge_news(list(groups), limit=limit)
