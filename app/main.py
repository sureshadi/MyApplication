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

from . import news, research, stocks, suggest
from .cache import TTLCache
from .config import Feed, Settings, Topic, get_settings

BASE_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None, analyst_factory=research.default_analyst) -> FastAPI:
    """`analyst_factory` builds the optional Claude analyst for market research. It returns None
    when ANTHROPIC_API_KEY is unset, and then the analysis is rule-based only."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            app.state.http = client
            yield

    app = FastAPI(title="Market Headlines", lifespan=lifespan)
    app.state.settings = settings
    app.state.cache = TTLCache(settings.cache_ttl_seconds)
    app.state.research_cache = TTLCache(settings.research_ttl_seconds)
    app.state.analyst = analyst_factory() if analyst_factory else None
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

    async def all_topic_news(request: Request, topic: Topic) -> list[news.NewsItem]:
        """Every headline from one themed tab's feeds, de-duplicated and newest first (cached)."""
        cache: TTLCache = request.app.state.cache
        key = f"topic:{topic.slug}"
        items = cache.get(key)
        if items is None:
            items = await news.fetch_all(request.app.state.http, topic.feeds)
            if items:
                cache.set(key, items)
        return items

    async def topic_news(request: Request, topic: Topic, feed: Feed | None = None) -> list[news.NewsItem]:
        """Headlines for a themed tab: a balanced mix of its feeds, or just one feed."""
        items = await all_topic_news(request, topic)
        if feed is not None:
            return [i for i in items if i.source == feed.source][: settings.max_items_single_source]
        per_source = -(-settings.max_items_per_topic // max(len(topic.feeds), 1))  # balanced mix
        return news.merge_news([items], limit=settings.max_items_per_topic, max_per_source=per_source)

    def find_topic(slug: str) -> Topic:
        for topic in settings.topics:
            if topic.slug == slug.lower():
                return topic
        raise HTTPException(status_code=404, detail=f"Unknown news topic '{slug[:30]}'")

    def find_source(slug: str | None, feeds: tuple[Feed, ...] | None = None) -> Feed | None:
        """The feed for a ?source= value. None means all sources; unknown values raise 404."""
        if not slug:
            return None
        for feed in feeds if feeds is not None else settings.feeds:
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

    def source_nav(items: list[news.NewsItem], feeds: tuple[Feed, ...] | None = None) -> list[dict]:
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
            for f in (feeds if feeds is not None else settings.feeds)
        ]

    async def cached_quote(request: Request, symbol: str) -> stocks.Quote:
        """Quote for an already-normalized symbol, cached. Raises QuoteNotFound / QuoteUnavailable."""
        cache: TTLCache = request.app.state.cache
        quote = cache.get(f"quote:{symbol}")
        if quote is None:
            quote = await stocks.get_quote(request.app.state.http, symbol, settings.finnhub_api_key)
            cache.set(f"quote:{symbol}", quote)
        return quote

    async def ticker_news(request: Request, symbol: str) -> list[news.NewsItem]:
        """Latest headlines about one company, newest first (cached)."""
        cache: TTLCache = request.app.state.cache
        items = cache.get(f"ticker_news:{symbol}")
        if items is None:
            related = await news.fetch_feed(
                request.app.state.http, Feed(source="Yahoo Finance", url=settings.ticker_news_url.format(symbol=symbol))
            )
            items = news.merge_news([related], limit=30)
            if items:
                cache.set(f"ticker_news:{symbol}", items)
        return items

    async def ticker_data(request: Request, raw_symbol: str):
        try:
            symbol = stocks.normalize_symbol(raw_symbol)
        except stocks.InvalidSymbol as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        cache: TTLCache = request.app.state.cache
        cached = cache.get(f"ticker:{symbol}")
        if cached is not None:
            return cached

        try:
            quote = await cached_quote(request, symbol)
        except stocks.QuoteNotFound:
            raise HTTPException(status_code=404, detail=f"No quote found for {symbol}")
        except stocks.QuoteUnavailable:
            raise HTTPException(status_code=503, detail="Stock data is temporarily unavailable")

        result = (quote, await ticker_news(request, symbol))
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
    async def topic_page(request: Request, slug: str, source: str | None = None):
        try:
            topic = find_topic(slug)
            feed = find_source(source, topic.feeds)
        except HTTPException as exc:
            return templates.TemplateResponse(
                request, "error.html", {"status": 404, "message": exc.detail}, status_code=404
            )
        items = await topic_news(request, topic, feed)
        return templates.TemplateResponse(
            request,
            "topic.html",
            {
                "topic": topic,
                "items": items,
                "sources": source_nav(await all_topic_news(request, topic), topic.feeds),
                "total_count": len(items) if feed is None else len(await topic_news(request, topic)),
                "active_source": feed,
                "active_tab": topic.slug,
            },
        )

    @app.get("/search")
    async def search(symbol: str = Query(..., min_length=1)):
        try:
            normalized = stocks.normalize_symbol(symbol)
        except stocks.InvalidSymbol:
            # Not a symbol: maybe a company name, like "apple". Use the best suggestion.
            words = symbol.split()
            best = suggest.local_matches(symbol, limit=1) or (suggest.local_matches(words[0], limit=1) if words else [])
            if best:
                return RedirectResponse(url=f"/ticker/{best[0].symbol}", status_code=303)
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

    @app.get("/api/suggest")
    async def api_suggest(request: Request, q: str = Query("", max_length=40)):
        """Ticker suggestions for the search box: matching symbols and company names."""
        query = q.strip()
        if not query:
            return {"query": "", "suggestions": []}
        cache: TTLCache = request.app.state.cache
        key = f"suggest:{query.lower()}"
        remote = cache.get(key)
        if remote is None:
            remote = await suggest.yahoo_matches(request.app.state.http, query)
            if remote:
                cache.set(key, remote)
        results = suggest.merge(suggest.local_matches(query), remote)
        return {"query": query, "suggestions": [s.to_dict() for s in results]}

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

    @app.get("/api/ticker/{symbol}/news")
    async def api_ticker_news(request: Request, symbol: str, limit: int = Query(3, ge=1, le=30)):
        """Top headlines for one company: what the My Portfolio side panel shows."""
        try:
            normalized = stocks.normalize_symbol(symbol)
        except stocks.InvalidSymbol as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        name = None
        try:
            name = (await cached_quote(request, normalized)).name
        except (stocks.QuoteNotFound, stocks.QuoteUnavailable):
            pass  # without a name, match on the ticker alone
        # Yahoo's per-ticker feed mixes in stories about other companies: keep the ones about this one.
        items = news.about_company(await ticker_news(request, normalized), normalized, name, limit)
        return {"symbol": normalized, "count": len(items), "items": [i.to_dict() for i in items]}

    async def sec_tickers(request: Request) -> dict | None:
        """SEC's ticker-to-CIK list, kept as long as analyses are."""
        cache: TTLCache = request.app.state.research_cache
        data = cache.get("sec_tickers")
        if data is None:
            try:
                resp = await request.app.state.http.get(
                    research.SEC_TICKERS_URL, headers={"User-Agent": settings.sec_user_agent}
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(status_code=503, detail="SEC EDGAR is temporarily unavailable") from exc
            cache.set("sec_tickers", data)
        return data

    @app.get("/api/research/{symbol}")
    async def api_research(request: Request, symbol: str):
        """Market research for one company: risks first, then fundamentals, drivers and guidance."""
        try:
            normalized = stocks.normalize_symbol(symbol)
        except stocks.InvalidSymbol as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        cache: TTLCache = request.app.state.research_cache
        cached = cache.get(f"research:{normalized}")
        if cached is not None:
            return cached

        price_change = None
        try:
            quote = await cached_quote(request, normalized)
            if len(quote.history) >= 2 and quote.history[0].close:
                price_change = round((quote.price - quote.history[0].close) / quote.history[0].close * 100, 1)
        except (stocks.QuoteNotFound, stocks.QuoteUnavailable):
            pass
        headlines = [i.to_dict() for i in await ticker_news(request, normalized)]
        try:
            analysis = await research.analyze(
                request.app.state.http,
                normalized,
                user_agent=settings.sec_user_agent,
                tickers=await sec_tickers(request),
                headlines=headlines,
                price_change_pct=price_change,
                analyst=request.app.state.analyst,
            )
        except research.CompanyNotFound:
            raise HTTPException(
                status_code=404,
                detail=f"No SEC filings found for {normalized}. Funds, ETFs and most non-US companies aren't covered.",
            )
        except research.ResearchUnavailable:
            raise HTTPException(status_code=503, detail="SEC EDGAR is temporarily unavailable")
        result = analysis.to_dict()
        cache.set(f"research:{normalized}", result)
        return result

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
