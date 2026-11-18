"""Stock quotes. Uses Finnhub when FINNHUB_API_KEY is set, otherwise Yahoo Finance's public chart endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .news import USER_AGENT

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

FINNHUB_BASE = "https://finnhub.io/api/v1"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class InvalidSymbol(ValueError):
    pass


class QuoteNotFound(LookupError):
    pass


class QuoteUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PricePoint:
    date: str  # YYYY-MM-DD
    close: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    change: float
    change_percent: float
    previous_close: float
    name: str | None = None
    currency: str | None = None
    day_high: float | None = None
    day_low: float | None = None
    as_of: datetime | None = None
    history: list[PricePoint] = field(default_factory=list)

    @property
    def direction(self) -> str:
        return "up" if self.change > 0 else "down" if self.change < 0 else "flat"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "change": self.change,
            "change_percent": self.change_percent,
            "previous_close": self.previous_close,
            "currency": self.currency,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "history": [{"date": p.date, "close": p.close} for p in self.history],
        }


def normalize_symbol(raw: str) -> str:
    """Upper-case and validate a ticker such as 'aapl' or 'BRK.B'."""
    symbol = (raw or "").strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise InvalidSymbol(f"'{raw}' is not a valid ticker symbol")
    return symbol


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def parse_yahoo_chart(symbol: str, data: dict) -> Quote:
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        raise QuoteNotFound(symbol)
    result = chart["result"][0]
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        raise QuoteNotFound(symbol)

    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    history = [
        PricePoint(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), round(c, 4))
        for t, c in zip(result.get("timestamp") or [], closes)
        if c is not None
    ]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if len(history) >= 2:
        prev = history[-2].close
    prev = prev or price
    change = price - prev
    return Quote(
        symbol=symbol,
        name=meta.get("longName") or meta.get("shortName"),
        price=round(price, 4),
        change=round(change, 4),
        change_percent=round(change / prev * 100, 2) if prev else 0.0,
        previous_close=round(prev, 4),
        currency=meta.get("currency"),
        day_high=meta.get("regularMarketDayHigh"),
        day_low=meta.get("regularMarketDayLow"),
        as_of=_ts(meta.get("regularMarketTime")),
        history=history,
    )


def parse_finnhub(symbol: str, quote: dict, profile: dict | None) -> Quote:
    # Finnhub returns all zeros for unknown symbols.
    if not quote or not quote.get("c"):
        raise QuoteNotFound(symbol)
    profile = profile or {}
    return Quote(
        symbol=symbol,
        name=profile.get("name"),
        price=quote["c"],
        change=quote.get("d") or 0.0,
        change_percent=quote.get("dp") or 0.0,
        previous_close=quote.get("pc") or quote["c"],
        currency=profile.get("currency"),
        day_high=quote.get("h"),
        day_low=quote.get("l"),
        as_of=_ts(quote.get("t")),
    )


async def get_quote(client: httpx.AsyncClient, symbol: str, finnhub_api_key: str | None = None) -> Quote:
    try:
        if finnhub_api_key:
            params = {"symbol": symbol, "token": finnhub_api_key}
            q = await client.get(f"{FINNHUB_BASE}/quote", params=params)
            q.raise_for_status()
            p = await client.get(f"{FINNHUB_BASE}/stock/profile2", params=params)
            profile = p.json() if p.status_code == 200 else None
            return parse_finnhub(symbol, q.json(), profile)

        resp = await client.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": "1mo", "interval": "1d"},
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code == 404:
            raise QuoteNotFound(symbol)
        resp.raise_for_status()
        return parse_yahoo_chart(symbol, resp.json())
    except httpx.HTTPError as exc:
        raise QuoteUnavailable(str(exc)) from exc
