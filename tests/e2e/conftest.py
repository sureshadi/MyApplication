"""Browser test setup.

By default the tests start the real app on a local port, with outside HTTP mocked.
Set BASE_URL to run against a deployed site instead, e.g.

    BASE_URL=https://market-headlines.onrender.com PORTFOLIO_USER=... PORTFOLIO_PASSWORD=... pytest -m e2e

Against a deployed site, tests marked `remote_safe` run. They check layout and behaviour (pages render, tabs
switch, the period picker changes values, dark mode toggles...) rather than exact headlines and prices.
Tests that also carry `local_only` check the mocked data exactly, so they only run against the local server.
Credentials then come from PORTFOLIO_USER and PORTFOLIO_PASSWORD.

The portfolio's tickers live in the browser's localStorage, and every test gets a fresh browser context,
so adding or removing tickers in a test never changes anyone's real portfolio.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import pytest
import respx
import uvicorn
from playwright.sync_api import expect

from app import auth
from app.main import create_app
from tests.conftest import TEST_PASSWORD, TEST_USER, install_default_routes, make_settings


BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
REMOTE = bool(BASE_URL)

if REMOTE:
    # A deployed site is slower than a local one (and Render's free plan wakes up from sleep).
    expect.set_options(timeout=20_000)


def pytest_collection_modifyitems(config, items):
    if not REMOTE:
        return
    skip = pytest.mark.skip(reason=f"needs the local test server with mocked data (BASE_URL={BASE_URL})")
    for item in items:
        if "e2e" in item.keywords and ("remote_safe" not in item.keywords or "local_only" in item.keywords):
            item.add_marker(skip)


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


# Formats that hold for any real price or change, used instead of exact mocked values on the live site.
PRICE = r"^\d[\d,]*\.\d\d$"
PERCENT = r"^[+-]?\d[\d,]*\.\d\d%$"


@pytest.fixture(scope="session")
def credentials() -> tuple[str, str]:
    """Portfolio username and password: test-only ones locally, the real ones from the environment remotely."""
    if not REMOTE:
        return TEST_USER, TEST_PASSWORD
    # Strip stray spaces and newlines, which are easy to paste into a CI secret by accident.
    user, password = os.getenv("PORTFOLIO_USER", "").strip(), os.getenv("PORTFOLIO_PASSWORD", "").strip()
    if not user or not password:
        pytest.exit("Set PORTFOLIO_USER and PORTFOLIO_PASSWORD to run the browser tests against BASE_URL", returncode=4)
    return user, password


def remote_sign_in(base_url: str, user: str, password: str) -> str:
    """Sign in over HTTP and return the session cookie. A successful sign-in also clears failed attempts."""
    r = httpx.post(f"{base_url}/login", data={"username": user, "password": password}, timeout=90)
    token = r.cookies.get(auth.COOKIE_NAME)
    if r.status_code != 303 or not token:
        pytest.exit(f"Could not sign in to {base_url} (HTTP {r.status_code}). Check PORTFOLIO_USER/PORTFOLIO_PASSWORD.", returncode=4)
    return token


def _wake_up(base_url: str) -> None:
    """Render's free plan sleeps when idle; the first request can take up to a minute."""
    deadline = time.time() + 180
    while True:
        try:
            if httpx.get(f"{base_url}/healthz", timeout=90).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.time() > deadline:
            pytest.exit(f"{base_url} did not respond", returncode=4)
        time.sleep(5)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_app():
    """The local app the browser tests talk to (lets tests reach its state, e.g. the sign-in throttle)."""
    if REMOTE:
        pytest.skip("needs the local test server")
    return create_app(make_settings(), analyst_factory=None)


@pytest.fixture(scope="session")
def live_server(request):
    """Base URL of the site under test: BASE_URL if set, otherwise a local server started here."""
    if REMOTE:
        _wake_up(BASE_URL)
        yield BASE_URL
        return
    live_app = request.getfixturevalue("live_app")
    port = _free_port()
    # Let requests to the local server itself through; everything else is mocked.
    with respx.mock(assert_all_called=False) as router:
        router.route(host="127.0.0.1").pass_through()
        install_default_routes(router)
        server = uvicorn.Server(uvicorn.Config(live_app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 10
        while not server.started:
            if time.time() > deadline:
                raise RuntimeError("live server did not start")
            time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(live_server):
    """Overrides pytest-playwright's own base_url fixture, which pytest 9.2+ warns about
    ("Session-scoped fixtures defined as instance methods are deprecated"). Also lets tests use page.goto("/...")."""
    return live_server


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Allow pointing at a preinstalled Chromium (e.g. in containers) via env var.
    path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return {**browser_type_launch_args, **({"executable_path": path} if path else {})}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, live_server, credentials):
    """Browser tests start signed in to Portfolio. Sign-in itself is tested with a fresh context (anon_page)."""
    if REMOTE:
        token = remote_sign_in(live_server, *credentials)
    else:
        token = auth.Authenticator(TEST_USER, TEST_PASSWORD, None, 86400).make_token()
    cookie = {"name": auth.COOKIE_NAME, "value": token, "url": live_server, "httpOnly": True, "sameSite": "Lax"}
    return {**browser_context_args, "storage_state": {"cookies": [cookie], "origins": []}}


@pytest.fixture
def anon_page(browser, live_server):
    """A page in a browser that hasn't signed in."""
    context = browser.new_context()
    if REMOTE:
        context.set_default_navigation_timeout(90_000)
    yield context.new_page()
    context.close()
