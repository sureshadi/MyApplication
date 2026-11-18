import httpx
import pytest

from app.stocks import (
    InvalidSymbol,
    QuoteNotFound,
    QuoteUnavailable,
    get_quote,
    normalize_symbol,
    parse_finnhub,
    parse_yahoo_chart,
)
from tests.conftest import fixture_json


class TestNormalizeSymbol:
    @pytest.mark.parametrize("raw,expected", [("aapl", "AAPL"), (" msft ", "MSFT"), ("brk.b", "BRK.B"), ("BF-B", "BF-B")])
    def test_valid(self, raw, expected):
        assert normalize_symbol(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "1ABC", "TOOLONGSYMBOL", "AA PL", "<script>", "../etc"])
    def test_invalid(self, raw):
        with pytest.raises(InvalidSymbol):
            normalize_symbol(raw)


class TestParseYahooChart:
    def test_parses_price_change_and_history(self):
        q = parse_yahoo_chart("AAPL", fixture_json("yahoo_chart_aapl.json"))
        assert q.name == "Apple Inc."
        assert q.price == 232.5
        assert q.previous_close == 230.0  # second-to-last close, null skipped
        assert q.change == 2.5
        assert q.change_percent == 1.09
        assert q.direction == "up"
        assert [p.close for p in q.history] == [225.0, 227.5, 230.0, 232.5]
        assert q.currency == "USD"

    def test_not_found(self):
        with pytest.raises(QuoteNotFound):
            parse_yahoo_chart("ZZZZ", fixture_json("yahoo_chart_notfound.json"))

    def test_missing_price_is_not_found(self):
        with pytest.raises(QuoteNotFound):
            parse_yahoo_chart("X", {"chart": {"result": [{"meta": {}}], "error": None}})


class TestParseFinnhub:
    def test_parses_quote_and_profile(self):
        q = parse_finnhub("MSFT", fixture_json("finnhub_quote_msft.json"), fixture_json("finnhub_profile_msft.json"))
        assert (q.name, q.price, q.change, q.change_percent) == ("Microsoft Corp", 415.2, -3.1, -0.74)
        assert q.direction == "down"

    def test_zero_price_means_unknown_symbol(self):
        with pytest.raises(QuoteNotFound):
            parse_finnhub("ZZZZ", {"c": 0, "d": None, "dp": None, "pc": 0}, None)


class TestGetQuote:
    async def test_uses_yahoo_without_api_key(self, mock_http):
        async with httpx.AsyncClient() as client:
            q = await get_quote(client, "AAPL")
        assert q.price == 232.5

    async def test_uses_finnhub_with_api_key(self, mock_http):
        async with httpx.AsyncClient() as client:
            q = await get_quote(client, "MSFT", finnhub_api_key="test-key")
        assert q.name == "Microsoft Corp"
        quote_calls = [c for c in mock_http.calls if c.request.url.path == "/api/v1/quote"]
        assert quote_calls[-1].request.url.params["token"] == "test-key"

    async def test_404_is_not_found(self, mock_http):
        async with httpx.AsyncClient() as client:
            with pytest.raises(QuoteNotFound):
                await get_quote(client, "ZZZZ")

    async def test_network_error_is_unavailable(self, mock_http):
        async with httpx.AsyncClient() as client:
            with pytest.raises(QuoteUnavailable):
                await get_quote(client, "DOWN")
