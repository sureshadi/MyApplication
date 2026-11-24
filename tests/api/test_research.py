"""/api/research/{symbol} and /api/ticker/{symbol}/news: what the My Portfolio research cards and side panel use."""

import httpx
from fastapi.testclient import TestClient

from app import research
from app.main import create_app
from tests.conftest import make_settings


def test_research_returns_risks_first_then_fundamentals(client):
    r = client.get("/api/research/aapl")
    assert r.status_code == 200
    data = r.json()
    assert list(data)[:6] == ["symbol", "name", "cik", "period", "headline", "risks"]
    assert data["symbol"] == "AAPL" and data["name"] == "Apple Inc." and data["cik"] == "0000320193"
    assert [x["title"] for x in data["risks"]] == ["Receivables growing faster than revenue", "Cash flow falling while earnings rise"]
    names = [m["name"] for m in data["metrics"]]
    assert names[:3] == ["Revenue", "Gross margin", "Operating income"]
    assert {"Free cash flow", "Total debt", "Diluted EPS"} <= set(names)
    assert data["analyst"] == "rules"
    assert data["disclaimer"].endswith("Not financial advice.")


def test_research_flags_a_loss_making_company_as_high_risk(client):
    risks = client.get("/api/research/LOSS").json()["risks"]
    assert [r["severity"] for r in risks[:2]] == ["high", "high"]


def test_research_unknown_company_is_404_with_reason(client):
    r = client.get("/api/research/SPY")
    assert r.status_code == 404
    assert "ETFs" in r.json()["detail"]


def test_research_invalid_symbol_is_400(client):
    assert client.get("/api/research/1BAD").status_code == 400


def test_research_is_cached(client, mock_http):
    client.get("/api/research/AAPL")
    facts_calls = lambda: sum(1 for c in mock_http.calls if "companyfacts" in str(c.request.url))
    before = facts_calls()
    assert client.get("/api/research/AAPL").status_code == 200
    assert facts_calls() == before == 1


def test_sec_ticker_list_is_fetched_once_for_many_companies(client, mock_http):
    for s in ("AAPL", "MSFT", "NVDA"):
        client.get(f"/api/research/{s}")
    assert sum(1 for c in mock_http.calls if str(c.request.url) == research.SEC_TICKERS_URL) == 1


def test_research_when_sec_is_down_is_503(mock_http):
    mock_http.get(research.SEC_TICKERS_URL).mock(side_effect=httpx.ConnectError("down"))
    with TestClient(create_app(make_settings(), analyst_factory=None)) as c:
        r = c.get("/api/research/AAPL")
    assert r.status_code == 503


def test_research_uses_claude_analyst_when_configured(mock_http):
    seen = []

    async def analyst(payload):
        seen.append(payload)
        return {"headline": "AI headline.", "drivers": ["d1"], "guidance": "g", "risks": [
            {"title": "Competition", "detail": "Headlines show price cuts.", "severity": "medium"}]}

    with TestClient(create_app(make_settings(), analyst_factory=lambda: analyst)) as c:
        data = c.get("/api/research/AAPL").json()
    assert data["analyst"] == "claude" and data["headline"] == "AI headline."
    assert "Competition" in [r["title"] for r in data["risks"]]
    # Claude gets the company's recent headlines and last month's price move.
    assert seen[0]["recent_headlines"][0]["title"] == "Apple unveils new AI features for iPhone"
    assert seen[0]["one_month_price_change_pct"] is not None


def test_ticker_news_returns_top_3_newest_first(client):
    data = client.get("/api/ticker/msft/news").json()
    assert data["symbol"] == "MSFT" and data["count"] == 3
    assert [i["title"] for i in data["items"]] == [
        "Microsoft cloud revenue tops estimates as AI demand grows",
        "Microsoft faces EU review of Teams bundling",
        "Microsoft raises dividend 10%",
    ]


def test_ticker_news_limit_and_validation(client):
    assert client.get("/api/ticker/MSFT/news?limit=1").json()["count"] == 1
    assert client.get("/api/ticker/MSFT/news?limit=0").status_code == 422
    assert client.get("/api/ticker/1BAD/news").status_code == 400
    assert client.get("/api/ticker/ZZZZ/news").json() == {"symbol": "ZZZZ", "count": 0, "items": []}


def test_ticker_news_does_not_need_a_quote(client, mock_http):
    client.get("/api/ticker/DOWN/news")  # the quote provider for DOWN is failing
    assert client.get("/api/ticker/DOWN/news").status_code == 200


def test_ticker_news_prefers_headlines_about_the_company(client):
    # The AMD feed has 2 stories about AMD (one only in its summary) among 3 about other companies.
    titles = [i["title"] for i in client.get("/api/ticker/AMD/news").json()["items"]]
    assert titles[:2] == ["AMD shares rise after new data center chip", "Chip stocks slip"]
    # Fewer than 3 are about AMD, so the newest other headline tops the list up to 3.
    assert titles[2] == "How risky is Snap stock now?"
    assert [i["title"] for i in client.get("/api/ticker/AMD/news?limit=2").json()["items"]] == titles[:2]


def test_ticker_news_matches_company_name_from_the_quote(client):
    # AAPL's quote name is "Apple Inc."; both AAPL headlines say "Apple", not "AAPL".
    titles = [i["title"] for i in client.get("/api/ticker/AAPL/news").json()["items"]]
    assert titles == ["Apple unveils new AI features for iPhone", "Analysts raise Apple price target"]
