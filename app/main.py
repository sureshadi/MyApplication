"""FastAPI app: a financial news front page and a per-ticker quote + news page."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import news, stocks
from .cache import TTLCache
from .config import Feed, Settings, get_settings

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
    templates.env.globals["watchlist"] = list(settings.watchlist)

    async def front_page_news(request: Request) -> list[news.NewsItem]:
        cache: TTLCache = request.app.state.cache
        items = cache.get("front_page")
        if items is None:
            items = await news.fetch_all(
                request.app.state.http,
                settings.feeds,
                limit=settings.max_front_page_items,
                max_per_source=settings.max_items_per_source,
            )
            if items:  # don't cache a total outage
                cache.set("front_page", items)
        return items

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
    async def index(request: Request):
        items = await front_page_news(request)
        return templates.TemplateResponse(request, "index.html", {"items": items})

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
            request, "ticker.html", {"quote": quote, "items": related, "active_symbol": quote.symbol}
        )

    # ---------- JSON API ----------

    @app.get("/api/news")
    async def api_news(request: Request):
        items = await front_page_news(request)
        return {"count": len(items), "items": [i.to_dict() for i in items]}

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
