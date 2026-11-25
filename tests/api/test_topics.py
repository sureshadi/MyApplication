"""Section tabs: Financial news (default), Technology news, Health news and Portfolio."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import HEALTH_URL, TECH_URL, make_settings


class TestTopicsApi:
    def test_technology_headlines(self, client):
        body = client.get("/api/topics/technology").json()
        assert body["topic"] == "technology" and body["title"] == "Technology"
        assert body["count"] == 3
        assert body["items"][0]["title"] == "Chipmakers race to build faster AI accelerators"

    def test_health_headlines_survive_a_broken_feed(self, client):
        body = client.get("/api/topics/HEALTH").json()
        assert [i["title"] for i in body["items"]] == [
            "Study links daily walks to better sleep",
            "FDA approves new treatment for migraines",
        ]

    def test_unknown_topic_404(self, client):
        assert client.get("/api/topics/sports").status_code == 404

    def test_topic_results_are_cached(self, client, mock_http):
        client.get("/api/topics/technology")
        client.get("/")
        assert mock_http.get(TECH_URL).call_count == 1

    def test_items_per_topic_limit(self, mock_http):
        with TestClient(create_app(make_settings(max_items_per_topic=2))) as c:
            assert c.get("/api/topics/technology").json()["count"] == 2


class TestTabs:
    def test_every_page_has_the_four_tabs_in_order(self, client):
        text = client.get("/").text
        positions = [text.index(f'data-tab="{t}"') for t in ("financial", "technology", "health", "portfolio")]
        assert positions == sorted(positions)
        for label in ("Financial", "Technology", "Health"):
            assert f'{label}<span class="tab-extra"> news</span>' in text
        assert "<span>Portfolio</span>" in text

    def test_financial_news_is_the_default_tab(self, client):
        text = client.get("/").text
        assert 'class="tab active" href="/" data-testid="tab" data-tab="financial" aria-current="page"' in text
        assert "Latest financial news" in text
        assert "Chipmakers race" not in text  # technology stays on its own tab

    def test_ticker_page_highlights_my_portfolio(self, client):
        assert 'data-tab="portfolio" aria-current="page"' in client.get("/ticker/AAPL").text


class TestTopicPages:
    def test_technology_page_shows_only_tech_news(self, client):
        r = client.get("/news/technology")
        assert r.status_code == 200
        assert "Latest technology news" in r.text
        assert 'data-tab="technology" aria-current="page"' in r.text
        assert r.text.count('data-testid="news-item"') == 3
        assert "Chipmakers race to build faster AI accelerators" in r.text
        assert "Stocks rally to record" not in r.text

    def test_health_page_shows_only_health_news(self, client):
        r = client.get("/news/health")
        assert "Latest health news" in r.text
        assert r.text.count('data-testid="news-item"') == 2
        assert "Study links daily walks to better sleep" in r.text
        assert "Chipmakers race" not in r.text

    def test_empty_topic_shows_message(self, mock_http):
        mock_http.get(HEALTH_URL).respond(500)
        with TestClient(create_app(make_settings())) as c:
            assert 'data-testid="no-news"' in c.get("/news/health").text

    def test_unknown_topic_page_404(self, client):
        assert client.get("/news/sports").status_code == 404


class TestPortfolioPage:
    def test_lists_every_default_ticker(self, client):
        r = client.get("/portfolio")
        assert r.status_code == 200
        assert 'data-tab="portfolio" aria-current="page"' in r.text
        assert r.text.count('data-testid="ticker-chip"') == 8
        for s in ("AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT"):
            assert f'data-symbol="{s}"' in r.text

    def test_news_pages_have_no_ticker_list(self, client):
        assert 'data-testid="ticker-chip"' not in client.get("/").text


class TestTopicSources:
    """Technology and Health tabs have the same Sources pane as Financial news."""

    def test_topic_page_lists_its_sources_with_counts(self, client):
        text = client.get("/news/health").text
        assert 'data-testid="source-sidebar"' in text
        assert '<a href="/news/health" class="source-link active" data-testid="source-link" data-slug="all"' in text
        assert 'href="/news/health?source=healthdaily"' in text
        assert 'href="/news/health?source=broken"' in text
        assert 'href="/?source=' not in text  # financial sources stay on the Financial tab

    def test_picking_a_source_filters_the_topic(self, mock_http):
        from app.config import Feed, Topic

        topics = (Topic("technology", "Technology", (Feed("TechWire", TECH_URL), Feed("HealthDaily", HEALTH_URL))),)
        with TestClient(create_app(make_settings(topics=topics))) as c:
            r = c.get("/news/technology", params={"source": "healthdaily"})
        assert r.status_code == 200
        assert "Technology news from HealthDaily" in r.text
        assert r.text.count('data-testid="news-item"') == 2
        assert "Chipmakers race" not in r.text
        assert 'data-slug="healthdaily"' in r.text and 'aria-current="page"' in r.text

    def test_unknown_topic_source_404(self, client):
        assert client.get("/news/technology", params={"source": "wsj"}).status_code == 404
