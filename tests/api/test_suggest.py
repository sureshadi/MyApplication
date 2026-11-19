"""Search box suggestions."""


def test_suggest_matches_symbol_and_name(client):
    body = client.get("/api/suggest", params={"q": "appl"}).json()
    assert body["query"] == "appl"
    assert body["suggestions"][0] == {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}


def test_suggest_adds_yahoo_results_for_less_common_tickers(client):
    body = client.get("/api/suggest", params={"q": "rivian"}).json()
    assert [s["symbol"] for s in body["suggestions"]] == ["RIVN"]  # options are left out


def test_suggest_merges_without_duplicates(client):
    syms = [s["symbol"] for s in client.get("/api/suggest", params={"q": "apple"}).json()["suggestions"]]
    assert syms[0] == "AAPL" and syms.count("AAPL") == 1 and "APLE" in syms


def test_suggest_still_works_when_yahoo_is_down(client):
    # "down" makes the mocked Yahoo search fail; built-in list still answers for known names.
    assert client.get("/api/suggest", params={"q": "down"}).json()["suggestions"] == []
    assert client.get("/api/suggest", params={"q": "nvidia"}).json()["suggestions"][0]["symbol"] == "NVDA"


def test_blank_query(client):
    assert client.get("/api/suggest", params={"q": "  "}).json() == {"query": "", "suggestions": []}


def test_suggest_is_cached(client, mock_http):
    from app.suggest import YAHOO_SEARCH_URL

    client.get("/api/suggest", params={"q": "rivian"})
    client.get("/api/suggest", params={"q": "Rivian"})
    assert mock_http.get(YAHOO_SEARCH_URL).call_count == 1


def test_search_with_company_name_opens_best_match(client):
    r = client.get("/search", params={"symbol": "tesla motors"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ticker/TSLA"


def test_search_box_has_suggestion_list(client):
    html = client.get("/").text
    assert 'role="combobox"' in html and 'aria-controls="search-suggestions"' in html
    assert 'id="search-suggestions" role="listbox"' in html


def test_search_blank_or_unknown_name_shows_invalid_message(client):
    for q in ("   ", "zzzz qqqq"):
        r = client.get("/search", params={"symbol": q}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/?error=invalid")
