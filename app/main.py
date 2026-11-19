"""FastAPI app: a financial news front page and a per-ticker quote + news page."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
from pathlib import Path

import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import news, stocks
from .cache import TTLCache
from .config import Feed, Settings, Topic, get_settings

BASE_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            app.state.http = client
            yield

    app = FastAPI(title="Market Headlines", lifespan=lifespan)
    app.state.settings = settings
    app.state.cache = TTLCache(settings.cache_ttl_seconds)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    def asset_version(path: str) -> str:
        """Short content hash of a static file, so each deploy gets new asset URLs and browsers
        never keep an old stylesheet or script from their cache."""
        try:
            return hashlib.sha256((BASE_DIR / "static" / path).read_bytes()).hexdigest()[:10]
        except OSError:
            return "0"

    asset_versions = {p: asset_version(p) for p in ("style.css", "app.js")}

    def asset_url(request: Request, path: str) -> str:
        version = asset_versions.get(path) or asset_version(path)
        return f"{request.url_for('static', path=path)}?v={version}"

    templates.env.globals["asset_url"] = asset_url
    templates.env.globals["watchlist"] = list(settings.watchlist)
    templates.env.globals["topics"] = [{"slug": t.slug, "title": t.title} for t in settings.topics]

    async def all_news(request: Request) -> list[news.NewsItem]:
        """Every headline from every front-page feed, de-duplicated and newest first (cached)."""
        cache: TTLCache = request.app.state.cache
        items = cache.get("all_news")
        if items is None:
            items = await news.fetch_all(request.app.state.http, settings.feeds)
            if items:  # don't cache a total outage
                cache.set("all_news", items)
        return items

    async def topic_news(request: Request, topic: Topic) -> list[news.NewsItem]:
        """Newest headlines for one themed section (cached, mixed across its feeds)."""
        cache: TTLCache = request.app.state.cache
        key = f"topic:{topic.slug}"
        items = cache.get(key)
        if items is None:
            items = await news.fetch_all(request.app.state.http, topic.feeds)
            if items:
                cache.set(key, items)
        per_source = -(-settings.max_items_per_topic // max(len(topic.feeds), 1))  # balanced mix
        return news.merge_news([items], limit=settings.max_items_per_topic, max_per_source=per_source)

    def find_topic(slug: str) -> Topic:
        for topic in settings.topics:
            if topic.slug == slug.lower():
                return topic
        raise HTTPException(status_code=404, detail=f"Unknown news topic '{slug[:30]}'")

    def find_source(slug: str | None) -> Feed | None:
        """The feed for a ?source= value. None means all sources; unknown values raise 404."""
        if not slug:
            return None
        for feed in settings.feeds:
            if feed.slug == slug.lower():
                return feed
        raise HTTPException(status_code=404, detail=f"Unknown news source '{slug[:30]}'")

    async def front_page_news(request: Request, feed: Feed | None = None) -> list[news.NewsItem]:
        items = await all_news(request)
        if feed is None:
            return news.merge_news(
                [items], limit=settings.max_front_page_items, max_per_source=settings.max_items_per_source
            )
        return [i for i in items if i.source == feed.source][: settings.max_items_single_source]

    def source_nav(items: list[news.NewsItem]) -> list[dict]:
        counts: dict[str, int] = {}
        for i in items:
            counts[i.source] = counts.get(i.source, 0) + 1
        return [
            {
                "slug": f.slug,
                "name": f.source,
                "label": f.label,
                "count": min(counts.get(f.source, 0), settings.max_items_single_source),
            }
            for f in settings.feeds
        ]

    async def cached_quote(request: Request, symbol: str) -> stocks.Quote:
        """Quote for an already-normalized symbol, cached. Raises QuoteNotFound / QuoteUnavailable."""
        cache: TTLCache = request.app.state.cache
        quote = cache.get(f"quote:{symbol}")
        if quote is None:
            quote = await stocks.get_quote(request.app.state.http, symbol, settings.finnhub_api_key)
            cache.set(f"quote:{symbol}", quote)
        return quote

    async def ticker_data(request: Request, raw_symbol: str):
        try:
            symbol = stocks.normalize_symbol(raw_symbol)
        except stocks.InvalidSymbol as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        cache: TTLCache = request.app.state.cache
        cached = cache.get(f"ticker:{symbol}")
        if cached is not None:
            return cached

        client: httpx.AsyncClient = request.app.state.http
        try:
            quote = await cached_quote(request, symbol)
        except stocks.QuoteNotFound:
            raise HTTPException(status_code=404, detail=f"No quote found for {symbol}")
        except stocks.QuoteUnavailable:
            raise HTTPException(status_code=503, detail="Stock data is temporarily unavailable")

        related = await news.fetch_feed(
            client, Feed(source="Yahoo Finance", url=settings.ticker_news_url.format(symbol=symbol))
        )
        result = (quote, news.merge_news([related], limit=30))
        cache.set(f"ticker:{symbol}", result)
        return result

    # ---------- HTML pages ----------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, source: str | None = None):
        try:
            feed = find_source(source)
        except HTTPException as exc:
            return templates.TemplateResponse(
                request, "error.html", {"status": 404, "message": exc.detail}, status_code=404
            )
        items = await front_page_news(request, feed)
        everything = await all_news(request)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "items": items,
                "sources": source_nav(everything),
                "total_count": len(items) if feed is None else len(await front_page_news(request, None)),
                "active_source": feed,
                "active_tab": "financial",
            },
        )

    @app.get("/portfolio", response_class=HTMLResponse)
    async def portfolio_page(request: Request):
        return templates.TemplateResponse(request, "portfolio.html", {"active_tab": "portfolio"})

    @app.get("/news/{slug}", response_class=HTMLResponse)
    async def topic_page(request: Request, slug: str):
        try:
            topic = find_topic(slug)
        except HTTPException as exc:
            return templates.TemplateResponse(
                request, "error.html", {"status": 404, "message": exc.detail}, status_code=404
            )
        return templates.TemplateResponse(
            request,
            "topic.html",
            {"topic": topic, "items": await topic_news(request, topic), "active_tab": topic.slug},
        )

    @app.get("/search")
    async def search(symbol: str = Query(..., min_length=1)):
        try:
            normalized = stocks.normalize_symbol(symbol)
        except stocks.InvalidSymbol:
            return RedirectResponse(url=f"/?error=invalid&symbol={symbol[:20]}", status_code=303)
        return RedirectResponse(url=f"/ticker/{normalized}", status_code=303)

    @app.get("/ticker/{symbol}", response_class=HTMLResponse)
    async def ticker_page(request: Request, symbol: str):
        try:
            quote, related = await ticker_data(request, symbol)
        except HTTPException as exc:
            return templates.TemplateResponse(
                request,
                "error.html",
                {"status": exc.status_code, "message": exc.detail, "symbol": symbol.upper()},
                status_code=exc.status_code,
            )
        return templates.TemplateResponse(
            request,
            "ticker.html",
            {"quote": quote, "items": related, "active_symbol": quote.symbol, "active_tab": "portfolio"},
        )

    # ---------- JSON API ----------

    @app.get("/api/news")
    async def api_news(request: Request, source: str | None = None):
        feed = find_source(source)
        items = await front_page_news(request, feed)
        return {"count": len(items), "source": feed.source if feed else None, "items": [i.to_dict() for i in items]}

    @app.get("/api/topics/{slug}")
    async def api_topic(request: Request, slug: str):
        topic = find_topic(slug)
        items = await topic_news(request, topic)
        return {"topic": topic.slug, "title": topic.title, "count": len(items), "items": [i.to_dict() for i in items]}

    @app.get("/api/sources")
    async def api_sources(request: Request):
        return {"sources": source_nav(await all_news(request))}

    @app.get("/api/quotes")
    async def api_quotes(request: Request, symbols: str | None = None):
        """Quotes for the top ticker bar. Unknown or unavailable symbols come back with an error, not a failure."""
        try:
            wanted = (
                stocks.parse_symbol_list(symbols, settings.max_quote_symbols)
                if symbols is not None
                else list(settings.watchlist)
            )
        except stocks.InvalidSymbol as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        async def one(symbol: str) -> dict:
            try:
                q = await cached_quote(request, symbol)
            except stocks.QuoteNotFound:
                return {"symbol": symbol, "error": "not_found"}
            except stocks.QuoteUnavailable:
                return {"symbol": symbol, "error": "unavailable"}
            return {
                "symbol": symbol,
                "name": q.name,
                "price": q.price,
                "change": q.change,
                "change_percent": q.change_percent,
                "currency": q.currency,
                "error": None,
            }

        return {"quotes": await asyncio.gather(*(one(s) for s in wanted))}

    @app.get("/api/ticker/{symbol}")
    async def api_ticker(request: Request, symbol: str):
        quote, related = await ticker_data(request, symbol)
        return {"quote": quote.to_dict(), "news": [i.to_dict() for i in related]}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
