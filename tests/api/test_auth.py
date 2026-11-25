"""Portfolio is behind a username and password; the news tabs stay public."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app
from tests.conftest import TEST_PASSWORD, TEST_USER, make_settings

PROTECTED_API = ["/api/performance?symbols=AAPL", "/api/research/AAPL", "/api/ticker/AAPL/news"]
PUBLIC = ["/", "/news/technology", "/news/health", "/ticker/AAPL", "/api/news", "/api/quotes", "/api/ticker/AAPL", "/healthz"]


def login(c, user=TEST_USER, password=TEST_PASSWORD, next_path=None):
    data = {"username": user, "password": password}
    if next_path is not None:
        data["next"] = next_path
    return c.post("/login", data=data, follow_redirects=False)


def test_portfolio_redirects_to_sign_in(anon_client):
    r = anon_client.get("/portfolio", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/portfolio"


@pytest.mark.parametrize("path", PROTECTED_API)
def test_portfolio_apis_need_sign_in(anon_client, path):
    r = anon_client.get(path)
    assert r.status_code == 401
    assert "Sign in" in r.json()["detail"]


@pytest.mark.parametrize("path", PUBLIC)
def test_news_and_ticker_pages_stay_public(anon_client, path):
    assert anon_client.get(path).status_code == 200


def test_sign_in_page(anon_client):
    r = anon_client.get("/login?next=/portfolio")
    assert r.status_code == 200
    assert 'data-testid="login-form"' in r.text
    assert 'name="next" value="/portfolio"' in r.text
    assert 'type="password"' in r.text
    assert 'data-tab="portfolio" aria-current="page"' in r.text
    assert 'data-testid="login-error"' not in r.text


def test_correct_password_opens_portfolio(anon_client):
    r = login(anon_client, next_path="/portfolio")
    assert r.status_code == 303 and r.headers["location"] == "/portfolio"
    cookie = r.headers["set-cookie"].lower()
    assert auth.COOKIE_NAME in cookie and "httponly" in cookie and "samesite=lax" in cookie
    page = anon_client.get("/portfolio")
    assert page.status_code == 200 and 'data-testid="portfolio"' in page.text
    assert 'data-testid="logout"' in page.text
    assert page.headers["cache-control"] == "private, no-store"
    assert anon_client.get("/api/research/AAPL").status_code == 200
    # Already signed in: the sign-in page goes straight on.
    assert anon_client.get("/login", follow_redirects=False).headers["location"] == "/portfolio"


def test_wrong_password_is_refused(anon_client):
    r = login(anon_client, password="nope")
    assert r.status_code == 401
    assert "Wrong username or password" in r.text
    assert auth.COOKIE_NAME not in r.headers.get("set-cookie", "")
    assert f'value="{TEST_USER}"' in r.text  # username kept, password not
    assert anon_client.get("/portfolio", follow_redirects=False).status_code == 303


def test_sign_in_never_redirects_off_site(anon_client):
    r = login(anon_client, next_path="https://evil.example/")
    assert r.headers["location"] == "/portfolio"


def test_too_many_wrong_passwords_are_throttled(anon_client):
    for _ in range(5):
        assert login(anon_client, password="nope").status_code == 401
    r = login(anon_client)  # even the right password waits
    assert r.status_code == 429 and "Too many attempts" in r.text


def test_sign_out(client):
    assert client.get("/portfolio").status_code == 200
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client.get("/portfolio", follow_redirects=False).status_code == 303


def test_forged_cookie_is_refused(anon_client):
    anon_client.cookies.set(auth.COOKIE_NAME, f"{TEST_USER}|9999999999|deadbeef")
    assert anon_client.get("/portfolio", follow_redirects=False).status_code == 303


def test_without_a_configured_password_portfolio_stays_locked(mock_http):
    with TestClient(create_app(make_settings(portfolio_password=None), analyst_factory=None)) as c:
        assert c.get("/portfolio", follow_redirects=False).status_code == 303
        assert "isn't set up" in c.get("/login").text
        r = login(c, password="")
        assert r.status_code == 503
        assert c.get("/api/research/AAPL").status_code == 401


def test_credentials_come_from_environment(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_USER", "someone")
    monkeypatch.setenv("PORTFOLIO_PASSWORD", "secret")
    from app.config import Settings

    s = Settings()
    assert (s.portfolio_user, s.portfolio_password) == ("someone", "secret")
