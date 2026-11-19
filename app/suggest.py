"""Ticker search suggestions: a built-in list of popular tickers (instant, always works)
merged with Yahoo Finance's public symbol search for everything else."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from .news import USER_AGENT

log = logging.getLogger(__name__)

YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_ALLOWED_TYPES = {"EQUITY", "ETF", "INDEX", "MUTUALFUND"}
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Suggestion:
    symbol: str
    name: str
    exchange: str = ""

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "name": self.name, "exchange": self.exchange}


# Well-known US stocks and ETFs, so common lookups get suggestions instantly even if Yahoo is slow.
POPULAR: tuple[Suggestion, ...] = tuple(
    Suggestion(s, n, e)
    for s, n, e in (
        ("AAPL", "Apple Inc.", "NASDAQ"), ("MSFT", "Microsoft Corporation", "NASDAQ"),
        ("NVDA", "NVIDIA Corporation", "NASDAQ"), ("GOOGL", "Alphabet Inc. Class A", "NASDAQ"),
        ("GOOG", "Alphabet Inc. Class C", "NASDAQ"), ("AMZN", "Amazon.com, Inc.", "NASDAQ"),
        ("META", "Meta Platforms, Inc.", "NASDAQ"), ("TSLA", "Tesla, Inc.", "NASDAQ"),
        ("AVGO", "Broadcom Inc.", "NASDAQ"), ("AMAT", "Applied Materials, Inc.", "NASDAQ"),
        ("AMD", "Advanced Micro Devices, Inc.", "NASDAQ"), ("INTC", "Intel Corporation", "NASDAQ"),
        ("QCOM", "QUALCOMM Incorporated", "NASDAQ"), ("TXN", "Texas Instruments Incorporated", "NASDAQ"),
        ("MU", "Micron Technology, Inc.", "NASDAQ"), ("ASML", "ASML Holding N.V.", "NASDAQ"),
        ("TSM", "Taiwan Semiconductor Manufacturing", "NYSE"), ("ARM", "Arm Holdings plc", "NASDAQ"),
        ("LRCX", "Lam Research Corporation", "NASDAQ"), ("KLAC", "KLA Corporation", "NASDAQ"),
        ("ORCL", "Oracle Corporation", "NYSE"), ("CRM", "Salesforce, Inc.", "NYSE"),
        ("ADBE", "Adobe Inc.", "NASDAQ"), ("NFLX", "Netflix, Inc.", "NASDAQ"),
        ("CSCO", "Cisco Systems, Inc.", "NASDAQ"), ("IBM", "International Business Machines", "NYSE"),
        ("NOW", "ServiceNow, Inc.", "NYSE"), ("INTU", "Intuit Inc.", "NASDAQ"),
        ("PLTR", "Palantir Technologies Inc.", "NASDAQ"), ("SHOP", "Shopify Inc.", "NYSE"),
        ("UBER", "Uber Technologies, Inc.", "NYSE"), ("ABNB", "Airbnb, Inc.", "NASDAQ"),
        ("PYPL", "PayPal Holdings, Inc.", "NASDAQ"), ("SQ", "Block, Inc.", "NYSE"),
        ("SNOW", "Snowflake Inc.", "NYSE"), ("PANW", "Palo Alto Networks, Inc.", "NASDAQ"),
        ("CRWD", "CrowdStrike Holdings, Inc.", "NASDAQ"), ("DELL", "Dell Technologies Inc.", "NYSE"),
        ("SMCI", "Super Micro Computer, Inc.", "NASDAQ"), ("COIN", "Coinbase Global, Inc.", "NASDAQ"),
        ("BRK-B", "Berkshire Hathaway Inc. Class B", "NYSE"), ("JPM", "JPMorgan Chase & Co.", "NYSE"),
        ("BAC", "Bank of America Corporation", "NYSE"), ("WFC", "Wells Fargo & Company", "NYSE"),
        ("GS", "The Goldman Sachs Group, Inc.", "NYSE"), ("MS", "Morgan Stanley", "NYSE"),
        ("C", "Citigroup Inc.", "NYSE"), ("V", "Visa Inc.", "NYSE"), ("MA", "Mastercard Incorporated", "NYSE"),
        ("AXP", "American Express Company", "NYSE"), ("BLK", "BlackRock, Inc.", "NYSE"),
        ("LLY", "Eli Lilly and Company", "NYSE"), ("UNH", "UnitedHealth Group Incorporated", "NYSE"),
        ("JNJ", "Johnson & Johnson", "NYSE"), ("PFE", "Pfizer Inc.", "NYSE"), ("MRK", "Merck & Co., Inc.", "NYSE"),
        ("ABBV", "AbbVie Inc.", "NYSE"), ("NVO", "Novo Nordisk A/S", "NYSE"), ("TMO", "Thermo Fisher Scientific", "NYSE"),
        ("ABT", "Abbott Laboratories", "NYSE"), ("AMGN", "Amgen Inc.", "NASDAQ"), ("MRNA", "Moderna, Inc.", "NASDAQ"),
        ("CVS", "CVS Health Corporation", "NYSE"), ("ISRG", "Intuitive Surgical, Inc.", "NASDAQ"),
        ("WMT", "Walmart Inc.", "NYSE"), ("COST", "Costco Wholesale Corporation", "NASDAQ"),
        ("HD", "The Home Depot, Inc.", "NYSE"), ("TGT", "Target Corporation", "NYSE"),
        ("NKE", "NIKE, Inc.", "NYSE"), ("MCD", "McDonald's Corporation", "NYSE"), ("SBUX", "Starbucks Corporation", "NASDAQ"),
        ("KO", "The Coca-Cola Company", "NYSE"), ("PEP", "PepsiCo, Inc.", "NASDAQ"),
        ("PG", "The Procter & Gamble Company", "NYSE"), ("DIS", "The Walt Disney Company", "NYSE"),
        ("XOM", "Exxon Mobil Corporation", "NYSE"), ("CVX", "Chevron Corporation", "NYSE"),
        ("BA", "The Boeing Company", "NYSE"), ("CAT", "Caterpillar Inc.", "NYSE"), ("GE", "GE Aerospace", "NYSE"),
        ("F", "Ford Motor Company", "NYSE"), ("GM", "General Motors Company", "NYSE"),
        ("T", "AT&T Inc.", "NYSE"), ("VZ", "Verizon Communications Inc.", "NYSE"),
        ("SPY", "SPDR S&P 500 ETF Trust", "NYSE Arca"), ("QQQ", "Invesco QQQ Trust", "NASDAQ"),
        ("VOO", "Vanguard S&P 500 ETF", "NYSE Arca"), ("VTI", "Vanguard Total Stock Market ETF", "NYSE Arca"),
        ("DIA", "SPDR Dow Jones Industrial Average ETF", "NYSE Arca"), ("IWM", "iShares Russell 2000 ETF", "NYSE Arca"),
    )
)


def _rank(s: Suggestion, q: str) -> int | None:
    """Lower is better; None means no match. Symbol prefix beats a name-word prefix."""
    sym, name_words = s.symbol.lower(), _WORD_RE.findall(s.name.lower())
    if sym == q:
        return 0
    if sym.startswith(q):
        return 1  # ties keep the list order, which puts the best-known companies first
    if any(w.startswith(q) for w in name_words) or s.name.lower().startswith(q):
        return 20
    q_words = _WORD_RE.findall(q)
    if len(q_words) > 1 and all(any(w.startswith(qw) for w in name_words) for qw in q_words):
        return 25  # every typed word starts a word of the name, e.g. "micro devices"
    if len(q) >= 3 and q in s.name.lower():
        return 30
    return None


def local_matches(query: str, limit: int = 8) -> list[Suggestion]:
    q = query.strip().lower()
    if not q:
        return []
    ranked = [(r, i, s) for i, s in enumerate(POPULAR) if (r := _rank(s, q)) is not None]
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [s for _, _, s in ranked[:limit]]


async def yahoo_matches(client: httpx.AsyncClient, query: str, limit: int = 8) -> list[Suggestion]:
    """Yahoo Finance symbol search. Any failure returns [] so suggestions still work from the built-in list."""
    try:
        resp = await client.get(
            YAHOO_SEARCH_URL,
            params={"q": query, "quotesCount": limit, "newsCount": 0, "listsCount": 0},
            headers={"User-Agent": USER_AGENT},
            timeout=3,
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Ticker search failed: %s", exc)
        return []
    out = []
    for q in quotes:
        symbol = (q.get("symbol") or "").upper()
        if not symbol or q.get("quoteType") not in _ALLOWED_TYPES:
            continue
        name = q.get("shortname") or q.get("longname") or ""
        out.append(Suggestion(symbol, name, q.get("exchDisp") or q.get("exchange") or ""))
    return out


def merge(*groups: list[Suggestion], limit: int = 8) -> list[Suggestion]:
    seen: set[str] = set()
    out: list[Suggestion] = []
    for group in groups:
        for s in group:
            if s.symbol not in seen:
                seen.add(s.symbol)
                out.append(s)
    return out[:limit]
