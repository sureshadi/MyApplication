"""Start the real app on a local port (with outside HTTP mocked) for browser tests."""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
import respx
import uvicorn

from app import auth
from app.main import create_app
from tests.conftest import TEST_PASSWORD, TEST_USER, install_default_routes, make_settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_app():
    """The app the browser tests talk to (lets tests reach its state, e.g. the sign-in throttle)."""
    return create_app(make_settings(), analyst_factory=None)


@pytest.fixture(scope="session")
def live_server(live_app):
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
def browser_type_launch_args(browser_type_launch_args):
    # Allow pointing at a preinstalled Chromium (e.g. in containers) via env var.
    path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return {**browser_type_launch_args, **({"executable_path": path} if path else {})}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, live_server):
    """Browser tests start signed in to Portfolio. Sign-in itself is tested with a fresh context (anon_page)."""
    token = auth.Authenticator(TEST_USER, TEST_PASSWORD, None, 86400).make_token()
    cookie = {"name": auth.COOKIE_NAME, "value": token, "url": live_server, "httpOnly": True, "sameSite": "Lax"}
    return {**browser_context_args, "storage_state": {"cookies": [cookie], "origins": []}}


@pytest.fixture
def anon_page(browser, live_server):
    """A page in a browser that hasn't signed in."""
    context = browser.new_context()
    yield context.new_page()
    context.close()
