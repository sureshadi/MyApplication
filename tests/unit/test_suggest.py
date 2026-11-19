import httpx
import pytest
import respx

from app.suggest import YAHOO_SEARCH_URL, Suggestion, local_matches, merge, yahoo_matches


def symbols(items):
    return [s.symbol for s in items]


class TestLocalMatches:
    def test_symbol_prefix(self):
        assert symbols(local_matches("aap"))[0] == "AAPL"
        assert symbols(local_matches("NV")) == ["NVDA", "NVO"]

    def test_exact_symbol_comes_first(self):
        assert symbols(local_matches("amd"))[0] == "AMD"

    def test_company_name(self):
        assert symbols(local_matches("apple"))[0] == "AAPL"
        assert symbols(local_matches("tesla")) == ["TSLA"]
        assert "MSFT" in symbols(local_matches("microsoft"))

    def test_blank_and_no_match(self):
        assert local_matches("   ") == []
        assert local_matches("zzzzqqq") == []

    def test_limit(self):
        assert len(local_matches("a", limit=3)) == 3


class TestYahooMatches:
    @pytest.mark.asyncio
    async def test_parses_and_keeps_only_stocks_and_funds(self):
        with respx.mock:
            respx.get(YAHOO_SEARCH_URL).respond(200, json={"quotes": [
                {"symbol": "rivn", "shortname": "Rivian Automotive, Inc.", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
                {"symbol": "RIVN240119C", "shortname": "opt", "quoteType": "OPTION"},
                {"symbol": "SPY", "longname": "SPDR S&P 500", "exchange": "PCX", "quoteType": "ETF"},
            ]})
            async with httpx.AsyncClient() as c:
                out = await yahoo_matches(c, "riv")
        assert out == [Suggestion("RIVN", "Rivian Automotive, Inc.", "NASDAQ"), Suggestion("SPY", "SPDR S&P 500", "PCX")]

    @pytest.mark.asyncio
    async def test_failure_returns_empty(self):
        with respx.mock:
            respx.get(YAHOO_SEARCH_URL).mock(side_effect=httpx.ConnectError("down"))
            async with httpx.AsyncClient() as c:
                assert await yahoo_matches(c, "x") == []


def test_merge_dedupes_and_limits():
    a = [Suggestion("AAPL", "Apple Inc.")]
    b = [Suggestion("AAPL", "Apple"), Suggestion("APLE", "Apple Hospitality")]
    assert symbols(merge(a, b)) == ["AAPL", "APLE"]
    assert symbols(merge(a, b, limit=1)) == ["AAPL"]
