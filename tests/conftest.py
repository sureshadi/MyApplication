"""Shared fixtures. All outside HTTP calls are mocked with respx, so tests never depend on live news."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import research
from app.config import Feed, Settings, Topic
from app.main import create_app
from app.stocks import FINNHUB_BASE, YAHOO_CHART_URL
from app.suggest import YAHOO_SEARCH_URL
from tests import sec_fixtures

FIXTURES = Path(__file__).parent / "fixtures"

CNBC_URL = "https://feeds.test/cnbc.xml"
MW_URL = "https://feeds.test/marketwatch.xml"
BROKEN_URL = "https://feeds.test/broken.xml"
TECH_URL = "https://feeds.test/tech.xml"
HEALTH_URL = "https://feeds.test/health.xml"
TICKER_NEWS_URL = "https://feeds.test/ticker/{symbol}.xml"


# Test-only Portfolio credentials (the real ones live in the host's environment settings).
TEST_USER = "tester"
TEST_PASSWORD = "test-password-123"


def sign_in(c: TestClient) -> TestClient:
    """Sign a test client in to Portfolio."""
    r = c.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict:
    return json.loads(fixture_bytes(name))


def make_settings(**overrides) -> Settings:
    values = dict(
        feeds=(Feed("CNBC", CNBC_URL), Feed("MarketWatch", MW_URL), Feed("Broken", BROKEN_URL)),
        topics=(
            Topic("technology", "Technology", (Feed("TechWire", TECH_URL),)),
            Topic("health", "Health", (Feed("HealthDaily", HEALTH_URL), Feed("Broken", BROKEN_URL))),
        ),
        ticker_news_url=TICKER_NEWS_URL,
        finnhub_api_key=None,
        cache_ttl_seconds=60,
        http_timeout_seconds=2,
        portfolio_user=TEST_USER,
        portfolio_password=TEST_PASSWORD,
        session_secret=None,
    )
    values.update(overrides)
    return Settings(**values)


def install_default_routes(router: respx.MockRouter) -> None:
    router.get(CNBC_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_cnbc.xml")))
    router.get(MW_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_marketwatch.xml")))
    router.get(BROKEN_URL).mock(return_value=httpx.Response(500))
    router.get(TECH_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_tech.xml")))
    router.get(HEALTH_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_health.xml")))
    router.get(TICKER_NEWS_URL.format(symbol="AAPL")).mock(
        return_value=httpx.Response(200, content=fixture_bytes("ticker_news_aapl.xml"))
    )
    router.get(TICKER_NEWS_URL.format(symbol="MSFT")).mock(
        return_value=httpx.Response(200, content=fixture_bytes("ticker_news_msft.xml"))
    )
    router.get(TICKER_NEWS_URL.format(symbol="AMD")).mock(
        return_value=httpx.Response(200, content=fixture_bytes("ticker_news_amd.xml"))
    )
    router.get(TICKER_NEWS_URL.format(symbol="ZZZZ")).mock(return_value=httpx.Response(200, content=b"<rss/>"))
    router.get(YAHOO_CHART_URL.format(symbol="AAPL")).mock(side_effect=_aapl_chart)
    router.get(YAHOO_CHART_URL.format(symbol="ZZZZ")).mock(
        return_value=httpx.Response(404, json=fixture_json("yahoo_chart_notfound.json"))
    )
    router.get(YAHOO_CHART_URL.format(symbol="DOWN")).mock(side_effect=httpx.ConnectError("boom"))
    # Any other symbol (e.g. the default watchlist) gets a generated quote; "NOPE*" symbols don't exist.
    router.get(url__regex=r"https://query1\.finance\.yahoo\.com/v8/finance/chart/[^/?]+").mock(side_effect=_generated_chart)
    router.get(url__regex=r"https://feeds\.test/ticker/[^/?]+\.xml").mock(return_value=httpx.Response(200, content=b"<rss/>"))
    router.get(YAHOO_SEARCH_URL).mock(side_effect=_yahoo_search)
    install_sec_routes(router)
    router.get(f"{FINNHUB_BASE}/quote").mock(return_value=httpx.Response(200, json=fixture_json("finnhub_quote_msft.json")))
    router.get(f"{FINNHUB_BASE}/stock/profile2").mock(
        return_value=httpx.Response(200, json=fixture_json("finnhub_profile_msft.json"))
    )


CIK_TO_NAME = {f"{r['cik_str']:010d}": r["title"] for r in sec_fixtures.SEC_TICKERS.values()}


def _sec_facts(request: httpx.Request) -> httpx.Response:
    cik = re.search(r"CIK(\d{10})", str(request.url)).group(1)
    name = CIK_TO_NAME.get(cik)
    if name is None:
        return httpx.Response(404)
    if name == "Loss Making Corp":
        facts = sec_fixtures.company_facts(name, revenue=(8.0e9, 10.0e9), net_income=(-1.2e9, 0.4e9))
    else:
        facts = sec_fixtures.company_facts(name)
    return httpx.Response(200, json=facts)


def _sec_submissions(request: httpx.Request) -> httpx.Response:
    cik = re.search(r"CIK(\d{10})", str(request.url)).group(1)
    name = CIK_TO_NAME.get(cik)
    return httpx.Response(200, json=sec_fixtures.submissions(name)) if name else httpx.Response(404)


def install_sec_routes(router: respx.MockRouter) -> None:
    router.get(research.SEC_TICKERS_URL).mock(return_value=httpx.Response(200, json=sec_fixtures.SEC_TICKERS))
    router.get(url__regex=r"https://data\.sec\.gov/api/xbrl/companyfacts/CIK\d{10}\.json").mock(side_effect=_sec_facts)
    router.get(url__regex=r"https://data\.sec\.gov/submissions/CIK\d{10}\.json").mock(side_effect=_sec_submissions)


@pytest.fixture(autouse=True)
def _no_claude_key(monkeypatch):
    """Tests never call the real Claude API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


YAHOO_SEARCH_RESULTS = {
    "rivian": [
        {"symbol": "RIVN", "shortname": "Rivian Automotive, Inc.", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        {"symbol": "RIVN240119C", "shortname": "Rivian option", "exchDisp": "OPR", "quoteType": "OPTION"},
    ],
    "apple": [
        {"symbol": "AAPL", "shortname": "Apple Inc.", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        {"symbol": "APLE", "shortname": "Apple Hospitality REIT, Inc.", "exchDisp": "NYSE", "quoteType": "EQUITY"},
    ],
}


def _yahoo_search(request: httpx.Request) -> httpx.Response:
    q = request.url.params.get("q", "").lower()
    if q == "down":
        return httpx.Response(503)
    return httpx.Response(200, json={"quotes": YAHOO_SEARCH_RESULTS.get(q, []), "news": []})


def generated_price(symbol: str) -> float:
    """Deterministic fake price per symbol, so tests can assert on it."""
    return float(100 + sum(ord(c) for c in symbol) % 400)


def history_drift(symbol: str) -> float:
    """How much higher (positive) or lower the price was five years ago, as a fraction of today's.

    LOSS was higher, so it is down over every period; the rest were lower, so they are up."""
    return 0.6 if symbol == "LOSS" else -0.3 - (sum(ord(c) for c in symbol) % 5) * 0.1


def _history_chart(symbol: str, price: float, name: str) -> httpx.Response:
    """Five years of weekly closes (what the period picker asks for), ending today."""
    now = int(time.time()) // 86400 * 86400
    weeks = 262
    ts = [now - 7 * 86400 * (weeks - 1 - i) for i in range(weeks)]
    closes = [round(price * (1 + history_drift(symbol) * (now - t) / (1826 * 86400)), 4) for t in ts]
    return httpx.Response(200, json={"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "currency": "USD", "longName": name, "regularMarketPrice": price},
        "timestamp": ts,
        "indicators": {"quote": [{"close": closes}]},
    }]}})


def _aapl_chart(request: httpx.Request) -> httpx.Response:
    data = fixture_json("yahoo_chart_aapl.json")
    if request.url.params.get("range") == "5y":
        meta = data["chart"]["result"][0]["meta"]
        return _history_chart("AAPL", meta["regularMarketPrice"], meta.get("longName") or "Apple Inc.")
    return httpx.Response(200, json=data)


def _generated_chart(request: httpx.Request) -> httpx.Response:
    symbol = re.search(r"/chart/([^/?]+)", str(request.url)).group(1)
    if symbol.startswith("NOPE"):
        return httpx.Response(404, json=fixture_json("yahoo_chart_notfound.json"))
    price = generated_price(symbol)
    if request.url.params.get("range") == "5y":
        return _history_chart(symbol, price, f"{symbol} Corp")
    data = {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "currency": "USD", "longName": f"{symbol} Corp", "regularMarketPrice": price},
        "timestamp": [1794931200, 1795017600],
        "indicators": {"quote": [{"close": [price - 1, price]}]},
    }]}}
    return httpx.Response(200, json=data)


@pytest.fixture
def mock_http():
    with respx.mock(assert_all_called=False) as router:
        install_default_routes(router)
        yield router


@pytest.fixture
def client(mock_http):
    """A visitor who has signed in to Portfolio."""
    with TestClient(create_app(make_settings(), analyst_factory=None)) as c:
        yield sign_in(c)


@pytest.fixture
def anon_client(mock_http):
    """A visitor who hasn't signed in."""
    with TestClient(create_app(make_settings(), analyst_factory=None)) as c:
        yield c
