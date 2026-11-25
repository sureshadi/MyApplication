from datetime import datetime, timezone

import httpx
import pytest

from app import stocks
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


class TestParseSymbolList:
    def test_normalizes_dedupes_and_keeps_order(self):
        from app.stocks import parse_symbol_list

        assert parse_symbol_list(" msft,aapl , MSFT,,googl") == ["MSFT", "AAPL", "GOOGL"]

    @pytest.mark.parametrize("raw", ["", " , ", "AAPL,1BAD", "AAPL,<x>"])
    def test_invalid(self, raw):
        from app.stocks import parse_symbol_list

        with pytest.raises(InvalidSymbol):
            parse_symbol_list(raw)

    def test_too_many(self):
        from app.stocks import parse_symbol_list

        with pytest.raises(InvalidSymbol, match="At most 2"):
            parse_symbol_list("A,B,C", max_count=2)


class TestPerformance:
    @staticmethod
    def chart(closes_by_day: dict[str, float], price: float) -> dict:
        days = sorted(closes_by_day)
        ts = [int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()) for d in days]
        return {"chart": {"error": None, "result": [{
            "meta": {"regularMarketPrice": price},
            "timestamp": ts,
            "indicators": {"quote": [{"close": [closes_by_day[d] for d in days]}]},
        }]}}

    def test_change_from_the_close_on_or_before_each_period_start(self):
        data = self.chart({
            "2021-11-20": 50.0, "2024-11-22": 80.0, "2025-11-21": 100.0, "2026-05-22": 110.0,
            "2026-08-21": 115.0, "2026-10-23": 118.0, "2026-11-24": 120.0,
        }, price=120.0)
        perf = stocks.parse_performance(data)
        assert perf == {"1D": 1.69, "1M": 1.69, "3M": 4.35, "6M": 9.09, "1Y": 20.0, "2Y": 50.0, "5Y": 140.0}

    def test_short_history_leaves_older_periods_empty(self):
        perf = stocks.parse_performance(self.chart({"2026-08-26": 10.0, "2026-11-24": 12.0}, price=12.0))
        # History starting two days after the 3M start still counts (weekends, holidays).
        assert perf["1M"] == 20.0 and perf["3M"] == 20.0
        assert perf["6M"] is None and perf["5Y"] is None

    def test_month_arithmetic_clamps_to_the_last_day(self):
        assert stocks._months_before(datetime(2026, 3, 31), 1) == datetime(2026, 2, 28)
        assert stocks._months_before(datetime(2026, 1, 15), 60) == datetime(2021, 1, 15)

    def test_unknown_symbol(self):
        with pytest.raises(stocks.QuoteNotFound):
            stocks.parse_performance({"chart": {"error": {"code": "Not Found"}, "result": None}})
