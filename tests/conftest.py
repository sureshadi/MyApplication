"""Shared fixtures. All outside HTTP calls are mocked with respx, so tests never depend on live news."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Feed, Settings
from app.main import create_app
from app.stocks import FINNHUB_BASE, YAHOO_CHART_URL

FIXTURES = Path(__file__).parent / "fixtures"

CNBC_URL = "https://feeds.test/cnbc.xml"
MW_URL = "https://feeds.test/marketwatch.xml"
BROKEN_URL = "https://feeds.test/broken.xml"
TICKER_NEWS_URL = "https://feeds.test/ticker/{symbol}.xml"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict:
    return json.loads(fixture_bytes(name))


def make_settings(**overrides) -> Settings:
    values = dict(
        feeds=(Feed("CNBC", CNBC_URL), Feed("MarketWatch", MW_URL), Feed("Broken", BROKEN_URL)),
        ticker_news_url=TICKER_NEWS_URL,
        finnhub_api_key=None,
        cache_ttl_seconds=60,
        http_timeout_seconds=2,
    )
    values.update(overrides)
    return Settings(**values)


def install_default_routes(router: respx.MockRouter) -> None:
    router.get(CNBC_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_cnbc.xml")))
    router.get(MW_URL).mock(return_value=httpx.Response(200, content=fixture_bytes("feed_marketwatch.xml")))
    router.get(BROKEN_URL).mock(return_value=httpx.Response(500))
    router.get(TICKER_NEWS_URL.format(symbol="AAPL")).mock(
        return_value=httpx.Response(200, content=fixture_bytes("ticker_news_aapl.xml"))
    )
    router.get(TICKER_NEWS_URL.format(symbol="ZZZZ")).mock(return_value=httpx.Response(200, content=b"<rss/>"))
    router.get(YAHOO_CHART_URL.format(symbol="AAPL")).mock(
        return_value=httpx.Response(200, json=fixture_json("yahoo_chart_aapl.json"))
    )
    router.get(YAHOO_CHART_URL.format(symbol="ZZZZ")).mock(
        return_value=httpx.Response(404, json=fixture_json("yahoo_chart_notfound.json"))
    )
    router.get(YAHOO_CHART_URL.format(symbol="DOWN")).mock(side_effect=httpx.ConnectError("boom"))
    router.get(f"{FINNHUB_BASE}/quote").mock(return_value=httpx.Response(200, json=fixture_json("finnhub_quote_msft.json")))
    router.get(f"{FINNHUB_BASE}/stock/profile2").mock(
        return_value=httpx.Response(200, json=fixture_json("finnhub_profile_msft.json"))
    )


@pytest.fixture
def mock_http():
    with respx.mock(assert_all_called=False) as router:
        install_default_routes(router)
        yield router


@pytest.fixture
def client(mock_http):
    with TestClient(create_app(make_settings())) as c:
        yield c
