import re

import pytest
from playwright.sync_api import Page, expect

from tests.conftest import generated_price

pytestmark = pytest.mark.e2e

DEFAULT = ["AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT"]


def chips(page: Page):
    return page.get_by_test_id("ticker-chip")


def chip(page: Page, symbol: str):
    return page.locator(f'[data-testid="ticker-chip"][data-symbol="{symbol}"]')


def add_ticker(page: Page, symbol: str):
    page.get_by_role("button", name="Add ticker").click()
    page.get_by_label("New ticker symbol").fill(symbol)
    page.get_by_role("button", name="Add", exact=True).click()


def test_bar_shows_default_tickers_with_live_prices(page: Page, live_server):
    page.goto(live_server)
    expect(chips(page)).to_have_count(len(DEFAULT))
    expect(chips(page).locator(".sym")).to_have_text(DEFAULT)
    expect(chip(page, "AAPL").locator(".px")).to_have_text("232.50")
    expect(chip(page, "AAPL").locator(".chg")).to_have_text("+1.09%")
    expect(chip(page, "AAPL").locator(".chg")).to_have_class(re.compile(r"\bup\b"))
    expect(chip(page, "NVDA").locator(".px")).to_have_text(f"{generated_price('NVDA'):,.2f}")
    expect(page.get_by_test_id("markets-chip")).to_have_class(re.compile(r"\bactive\b"))


def test_clicking_a_ticker_opens_its_page_and_highlights_it(page: Page, live_server):
    page.goto(live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(page).to_have_url(re.compile(r"/ticker/MSFT$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("MSFT")
    expect(chip(page, "MSFT")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.get_by_test_id("markets-chip")).not_to_have_class(re.compile(r"\bactive\b"))
    page.get_by_test_id("markets-chip").click()
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()


def test_add_ticker_with_plus_button_persists_after_reload(page: Page, live_server):
    page.goto(live_server)
    add_ticker(page, "tsla")
    expect(chip(page, "TSLA")).to_be_visible()
    expect(chip(page, "TSLA").locator(".px")).to_have_text(f"{generated_price('TSLA'):,.2f}")
    expect(page.get_by_test_id("add-form")).to_be_hidden()
    expect(chips(page)).to_have_count(len(DEFAULT) + 1)

    page.reload()
    expect(chips(page).locator(".sym")).to_have_text(DEFAULT + ["TSLA"])
    page.goto(f"{live_server}/ticker/TSLA")
    expect(chip(page, "TSLA")).to_have_class(re.compile(r"\bactive\b"))


def test_remove_ticker_persists_after_reload(page: Page, live_server):
    page.goto(live_server)
    chip(page, "LLY").hover()
    page.get_by_role("button", name="Remove LLY").click()
    expect(chip(page, "LLY")).to_have_count(0)
    page.reload()
    expect(chips(page)).to_have_count(len(DEFAULT) - 1)
    expect(chip(page, "LLY")).to_have_count(0)


def test_add_rejects_invalid_duplicate_and_unknown_tickers(page: Page, live_server):
    page.goto(live_server)
    add_ticker(page, "1BAD")
    expect(page.get_by_test_id("add-error")).to_have_text("Enter a valid ticker symbol, like TSLA.")

    page.get_by_label("New ticker symbol").fill("aapl")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("AAPL is already in your bar.")

    page.get_by_label("New ticker symbol").fill("NOPEX")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("Couldn't find NOPEX.")
    expect(chips(page)).to_have_count(len(DEFAULT))


def test_add_form_can_be_cancelled(page: Page, live_server):
    page.goto(live_server)
    page.get_by_role("button", name="Add ticker").click()
    expect(page.get_by_test_id("add-form")).to_be_visible()
    page.get_by_label("New ticker symbol").press("Escape")
    expect(page.get_by_test_id("add-form")).to_be_hidden()


def test_front_page_features_a_top_story(page: Page, live_server):
    page.goto(live_server)
    featured = page.locator(".news-item.featured")
    expect(featured).to_have_count(1)
    expect(featured).to_contain_text("Stocks rally to record")


def test_bar_fits_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server)
    expect(page.get_by_role("button", name="Add ticker")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
