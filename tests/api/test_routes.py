from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CNBC_URL, make_settings


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


class TestNewsApi:
    def test_returns_merged_deduped_news(self, client):
        body = client.get("/api/news").json()
        titles = [i["title"] for i in body["items"]]
        assert body["count"] == len(titles) == 4
        assert titles[0] == "Stocks rally to record as tech leads gains"
        assert body["items"][0]["source"] == "MarketWatch"
        assert body["items"][0]["published"] == "2026-11-18T16:45:00+00:00"

    def test_results_are_cached(self, client, mock_http):
        client.get("/api/news")
        client.get("/api/news")
        assert mock_http.get(CNBC_URL).call_count == 1

    def test_per_source_cap_applies_to_front_page(self, mock_http):
        with TestClient(create_app(make_settings(max_items_per_source=1))) as c:
            items = c.get("/api/news").json()["items"]
        assert [i["source"] for i in items] == ["MarketWatch", "CNBC"]

    def test_all_feeds_down_returns_empty_list(self, mock_http):
        mock_http.get(CNBC_URL).respond(500)
        mock_http.get("https://feeds.test/marketwatch.xml").respond(500)
        with TestClient(create_app(make_settings())) as c:
            assert c.get("/api/news").json() == {"count": 0, "source": None, "items": []}


class TestTickerApi:
    def test_quote_and_related_news(self, client):
        body = client.get("/api/ticker/aapl").json()
        assert body["quote"]["symbol"] == "AAPL"
        assert body["quote"]["price"] == 232.5
        assert len(body["quote"]["history"]) == 4
        assert [n["title"] for n in body["news"]][0] == "Apple unveils new AI features for iPhone"

    def test_invalid_symbol_400(self, client):
        assert client.get("/api/ticker/1BAD").status_code == 400

    def test_unknown_symbol_404(self, client):
        assert client.get("/api/ticker/ZZZZ").status_code == 404

    def test_provider_down_503(self, client):
        assert client.get("/api/ticker/DOWN").status_code == 503

    def test_finnhub_used_when_key_configured(self, mock_http):
        mock_http.get("https://feeds.test/ticker/MSFT.xml").respond(200, content=b"<rss/>")
        with TestClient(create_app(make_settings(finnhub_api_key="k"))) as c:
            body = c.get("/api/ticker/MSFT").json()
        assert body["quote"]["name"] == "Microsoft Corp"
        assert body["news"] == []


class TestHtmlPages:
    def test_front_page_lists_headlines(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Latest financial news" in r.text
        assert r.text.count('data-testid="news-item"') == 4
        assert 'target="_blank" rel="noopener noreferrer"' in r.text

    def test_front_page_empty_state(self, mock_http):
        mock_http.get(CNBC_URL).respond(500)
        mock_http.get("https://feeds.test/marketwatch.xml").respond(500)
        with TestClient(create_app(make_settings())) as c:
            assert 'data-testid="no-news"' in c.get("/").text

    def test_search_redirects_to_normalized_ticker(self, client):
        r = client.get("/search", params={"symbol": " aapl "}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/ticker/AAPL"

    def test_search_invalid_symbol_shows_message(self, client):
        r = client.get("/search", params={"symbol": "1BAD"})
        assert 'data-testid="invalid-symbol"' in r.text

    def test_ticker_page(self, client):
        r = client.get("/ticker/AAPL")
        assert r.status_code == 200
        assert "Apple Inc." in r.text and "232.50" in r.text and "+2.50 (+1.09%)" in r.text
        assert 'data-testid="price-chart"' in r.text

    def test_ticker_page_not_found(self, client):
        r = client.get("/ticker/ZZZZ")
        assert r.status_code == 404 and "Symbol not found" in r.text

    def test_html_is_escaped(self, mock_http):
        mock_http.get(CNBC_URL).respond(
            200,
            content=b"<rss><channel><item><title>AT&amp;amp;T &amp;lt;b&amp;gt;bold</title>"
            b"<link>https://x.test/a</link></item></channel></rss>",
        )
        with TestClient(create_app(make_settings())) as c:
            text = c.get("/").text
        assert "<b>bold" not in text
        assert "AT&amp;T &lt;b&gt;bold" in text
