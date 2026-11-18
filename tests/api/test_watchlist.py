"""Top ticker bar: /api/quotes and the bar markup on every page."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import generated_price, make_settings

DEFAULT = ["AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT"]


class TestQuotesApi:
    def test_defaults_to_watchlist(self, client):
        quotes = client.get("/api/quotes").json()["quotes"]
        assert [q["symbol"] for q in quotes] == DEFAULT
        assert all(q["error"] is None for q in quotes)

    def test_quote_fields(self, client):
        q = client.get("/api/quotes", params={"symbols": "nvda"}).json()["quotes"][0]
        assert q == {
            "symbol": "NVDA",
            "name": "NVDA Corp",
            "price": generated_price("NVDA"),
            "change": 1.0,
            "change_percent": round(1 / (generated_price("NVDA") - 1) * 100, 2),
            "currency": "USD",
            "error": None,
        }

    def test_explicit_symbols_are_normalized_and_deduped(self, client):
        quotes = client.get("/api/quotes", params={"symbols": "tsla, aapl,TSLA"}).json()["quotes"]
        assert [q["symbol"] for q in quotes] == ["TSLA", "AAPL"]
        assert quotes[1]["price"] == 232.5  # AAPL fixture

    def test_unknown_symbol_returns_error_entry(self, client):
        quotes = client.get("/api/quotes", params={"symbols": "AAPL,NOPEX"}).json()["quotes"]
        assert quotes[1] == {"symbol": "NOPEX", "error": "not_found"}
        assert quotes[0]["error"] is None

    def test_provider_down_returns_unavailable_entry(self, client):
        quotes = client.get("/api/quotes", params={"symbols": "DOWN"}).json()["quotes"]
        assert quotes == [{"symbol": "DOWN", "error": "unavailable"}]

    def test_invalid_symbol_is_400(self, client):
        assert client.get("/api/quotes", params={"symbols": "AAPL,1BAD"}).status_code == 400

    def test_empty_symbols_is_400(self, client):
        assert client.get("/api/quotes", params={"symbols": ""}).status_code == 400

    def test_too_many_symbols_is_400(self, client):
        many = ",".join(f"T{chr(65 + i)}" for i in range(26))
        r = client.get("/api/quotes", params={"symbols": many})
        assert r.status_code == 400 and "At most 25" in r.json()["detail"]

    def test_quotes_are_cached(self, client, mock_http):
        client.get("/api/quotes", params={"symbols": "AAPL"})
        client.get("/api/quotes", params={"symbols": "AAPL"})
        client.get("/ticker/AAPL")  # ticker page reuses the cached quote
        aapl_calls = [c for c in mock_http.calls if c.request.url.path.endswith("/chart/AAPL")]
        assert len(aapl_calls) == 1


class TestTickerBarMarkup:
    def test_front_page_has_bar_with_default_tickers_and_add_button(self, client):
        html = client.get("/").text
        assert 'data-testid="ticker-bar"' in html
        assert html.count('data-testid="ticker-chip"') == len(DEFAULT)
        for s in DEFAULT:
            assert f'href="/ticker/{s}"' in html
        assert 'data-testid="add-ticker"' in html and 'aria-label="Add ticker"' in html
        assert 'data-default="' + ",".join(DEFAULT) + '"' in html

    def test_markets_chip_active_on_front_page(self, client):
        html = client.get("/").text
        assert 'class="chip chip-markets active"' in html

    def test_ticker_page_marks_its_chip_active(self, client):
        html = client.get("/ticker/MSFT").text
        assert 'class="chip ticker-chip active" data-symbol="MSFT"' in html
        assert 'class="chip chip-markets active"' not in html
        assert 'data-active="MSFT"' in html

    def test_bar_appears_on_error_pages(self, client):
        assert 'data-testid="ticker-bar"' in client.get("/ticker/ZZZZ").text

    def test_watchlist_is_configurable(self, mock_http):
        with TestClient(create_app(make_settings(watchlist=("TSLA", "AMD")))) as c:
            html = c.get("/").text
            assert html.count('data-testid="ticker-chip"') == 2
            assert [q["symbol"] for q in c.get("/api/quotes").json()["quotes"]] == ["TSLA", "AMD"]

    def test_front_page_features_top_story(self, client):
        html = client.get("/").text
        assert html.count('class="news-item featured"') == 1
        assert 'class="news-item featured"' not in client.get("/ticker/AAPL").text

    def test_script_is_served(self, client):
        r = client.get("/static/app.js")
        assert r.status_code == 200 and "mh.watchlist.v1" in r.text
