"""Signing in to Portfolio in a real browser."""

import re

import pytest
from playwright.sync_api import expect

from tests.conftest import TEST_PASSWORD, TEST_USER

pytestmark = pytest.mark.e2e


def test_portfolio_tab_asks_to_sign_in_then_opens(anon_page, live_server):
    page = anon_page
    page.goto(f"{live_server}/")
    page.locator("[data-tab=portfolio]").click()
    expect(page).to_have_url(re.compile(r"/login\?next=/portfolio$"))
    expect(page.get_by_role("heading", name="Sign in to Portfolio")).to_be_visible()

    page.get_by_label("Username").fill(TEST_USER)
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_test_id("login-error")).to_have_text("Wrong username or password.")
    expect(page.get_by_label("Username")).to_have_value(TEST_USER)

    page.get_by_label("Password").fill(TEST_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(re.compile(r"/portfolio$"))
    expect(page.get_by_test_id("ticker-chip")).to_have_count(8)
    expect(page.get_by_test_id("research-tabs").get_by_role("tab")).to_have_count(8)

    page.get_by_test_id("logout").click()
    expect(page).to_have_url(re.compile(r"/$"))
    page.goto(f"{live_server}/portfolio")
    expect(page).to_have_url(re.compile(r"/login"))


def test_news_tabs_need_no_sign_in(anon_page, live_server):
    page = anon_page
    for path in ("/", "/news/technology", "/news/health"):
        page.goto(f"{live_server}{path}")
        expect(page).to_have_url(f"{live_server}{path}")
        expect(page.get_by_test_id("login")).to_have_count(0)
