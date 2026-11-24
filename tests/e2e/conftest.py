"""Start the real app on a local port (with outside HTTP mocked) for browser tests."""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
import respx
import uvicorn

from app.main import create_app
from tests.conftest import install_default_routes, make_settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    port = _free_port()
    # Let requests to the local server itself through; everything else is mocked.
    with respx.mock(assert_all_called=False) as router:
        router.route(host="127.0.0.1").pass_through()
        install_default_routes(router)
        server = uvicorn.Server(uvicorn.Config(create_app(make_settings(), analyst_factory=None), host="127.0.0.1", port=port, log_level="warning"))
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
