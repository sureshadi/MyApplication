"""Technology and Health sections at the top of the front page."""

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


class TestFrontPageTopics:
    def test_tech_and_health_sections_come_before_financial_news(self, client):
        text = client.get("/").text
        tech = text.index('data-topic="technology"')
        health = text.index('data-topic="health"')
        finance = text.index("Latest financial news")
        assert tech < health < finance
        assert text.count('data-testid="topic-item"') == 5
        assert "Chipmakers race to build faster AI accelerators" in text
        assert "Study links daily walks to better sleep" in text

    def test_sections_hidden_when_one_source_is_picked(self, client):
        assert 'data-testid="topic-sections"' not in client.get("/?source=cnbc").text

    def test_empty_topic_shows_message(self, mock_http):
        mock_http.get(HEALTH_URL).respond(500)
        with TestClient(create_app(make_settings())) as c:
            text = c.get("/").text
        assert "No health headlines right now." in text
        assert 'data-topic="technology"' in text


class TestPortfolioTab:
    def test_front_page_tickers_are_tucked_into_my_portfolio(self, client):
        text = client.get("/").text
        assert "My Portfolio" in text
        assert 'aria-expanded="false"' in text
        assert 'id="portfolio" data-testid="portfolio" hidden' in text
        assert 'data-testid="portfolio-count">8<' in text

    def test_ticker_page_opens_portfolio(self, client):
        text = client.get("/ticker/AAPL").text
        assert 'aria-expanded="true"' in text
        assert 'data-testid="portfolio" hidden' not in text
