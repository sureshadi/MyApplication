"""Left sidebar: filter the front page and /api/news by news source."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import CNBC_URL, make_settings


class TestNewsApiBySource:
    def test_filters_to_one_source(self, client):
        body = client.get("/api/news", params={"source": "cnbc"}).json()
        assert body["source"] == "CNBC"
        assert body["count"] == 2
        assert {i["source"] for i in body["items"]} == {"CNBC"}

    def test_source_is_case_insensitive(self, client):
        assert client.get("/api/news", params={"source": "MarketWatch"}).json()["count"] == 2

    def test_unknown_source_is_404(self, client):
        r = client.get("/api/news", params={"source": "bloomberg"})
        assert r.status_code == 404 and "Unknown news source" in r.json()["detail"]

    def test_all_sources_when_not_given(self, client):
        body = client.get("/api/news").json()
        assert body["source"] is None and body["count"] == 4

    def test_single_source_limit(self, mock_http):
        with TestClient(create_app(make_settings(max_items_single_source=1))) as c:
            assert c.get("/api/news", params={"source": "cnbc"}).json()["count"] == 1

    def test_feeds_fetched_once_across_filters(self, client, mock_http):
        client.get("/api/news")
        client.get("/api/news", params={"source": "cnbc"})
        client.get("/?source=marketwatch")
        assert mock_http.get(CNBC_URL).call_count == 1


class TestSourcesApi:
    def test_lists_every_feed_with_counts(self, client):
        assert client.get("/api/sources").json()["sources"] == [
            {"slug": "cnbc", "name": "CNBC", "label": "CNBC", "count": 2},
            {"slug": "marketwatch", "name": "MarketWatch", "label": "MarketWatch", "count": 2},
            {"slug": "broken", "name": "Broken", "label": "Broken", "count": 0},
        ]


class TestSidebar:
    def test_front_page_has_sidebar_with_all_and_each_source(self, client):
        html = client.get("/").text
        assert 'data-testid="source-sidebar"' in html
        assert html.count('data-testid="source-link"') == 4  # All + 3 feeds
        for slug in ("cnbc", "marketwatch", "broken"):
            assert f'href="/?source={slug}"' in html

    def test_all_sources_active_by_default(self, client):
        html = client.get("/").text
        assert 'class="source-link active" data-testid="source-link" data-slug="all"' in html
        assert html.count('aria-current="page"') == 1

    def test_selected_source_filters_page(self, client):
        r = client.get("/", params={"source": "cnbc"})
        assert r.status_code == 200
        assert "Latest from CNBC" in r.text
        assert r.text.count('data-testid="news-item"') == 2
        assert "Stocks rally to record" not in r.text  # MarketWatch story is filtered out
        assert 'class="source-link active" data-testid="source-link" data-slug="cnbc"' in r.text
        assert "<title>CNBC · Market Headlines</title>" in r.text

    def test_source_with_no_headlines_shows_empty_state(self, client):
        assert 'data-testid="no-news"' in client.get("/", params={"source": "broken"}).text

    def test_unknown_source_page_is_404(self, client):
        r = client.get("/", params={"source": "nope"})
        assert r.status_code == 404 and "Unknown news source" in r.text

    def test_all_sources_count_matches_headlines_shown(self, mock_http):
        # With a cap of 1 per source, "All sources" shows 2 headlines (1 CNBC + 1 MarketWatch), not 4.
        with TestClient(create_app(make_settings(max_items_per_source=1))) as c:
            html = c.get("/").text
            assert html.count('data-testid="news-item"') == 2
            assert 'data-slug="all"' in html and '<span class="source-count">2</span>' in html.split('data-slug="all"')[1].split("</a>")[0]
            html_cnbc = c.get("/", params={"source": "cnbc"}).text
            assert '<span class="source-count">2</span>' in html_cnbc.split('data-slug="all"')[1].split("</a>")[0]

    def test_counts_shown_in_sidebar(self, client):
        html = client.get("/").text
        assert '<span class="source-count">4</span>' in html
        assert html.count('<span class="source-count">2</span>') == 2
