from app.config import DEFAULT_WATCHLIST, Settings


def test_default_watchlist_has_requested_companies(monkeypatch):
    monkeypatch.delenv("WATCHLIST", raising=False)
    assert Settings().watchlist == ("AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT")
    assert DEFAULT_WATCHLIST.split(",") == list(Settings().watchlist)


def test_watchlist_from_env_is_normalized(monkeypatch):
    monkeypatch.setenv("WATCHLIST", " tsla, amd ,,nflx ")
    assert Settings().watchlist == ("TSLA", "AMD", "NFLX")


def test_front_page_sources_are_wsj_nyt_cnbc_ft():
    assert {f.source for f in Settings().feeds} == {"Wall Street Journal", "New York Times", "CNBC", "Financial Times"}
