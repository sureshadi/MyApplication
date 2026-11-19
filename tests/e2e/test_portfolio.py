"""My Portfolio tab: every ticker shows at once with live prices; add and remove are saved in this browser."""

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


def open_portfolio(page: Page, live_server: str):
    page.goto(live_server)
    page.get_by_role("link", name="My Portfolio").click()
    expect(page).to_have_url(re.compile(r"/portfolio$"))


def add_ticker(page: Page, symbol: str):
    page.get_by_role("button", name="Add ticker").click()
    page.get_by_label("New ticker symbol").fill(symbol)
    page.get_by_role("button", name="Add", exact=True).click()


@pytest.mark.parametrize("width", [1280, 375])
def test_clicking_my_portfolio_shows_every_ticker(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 900})
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="My Portfolio")).to_be_visible()
    expect(chips(page)).to_have_count(len(DEFAULT))
    expect(chips(page).locator(".sym")).to_have_text(DEFAULT)
    # Every ticker is laid out on screen (wrapping grid), none hidden in a sideways scroller.
    for symbol in DEFAULT:
        chip(page, symbol).scroll_into_view_if_needed()
        expect(chip(page, symbol)).to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_portfolio_shows_live_prices(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(chip(page, "AAPL").locator(".px")).to_have_text("232.50")
    expect(chip(page, "AAPL").locator(".chg")).to_have_text("+1.09%")
    expect(chip(page, "AAPL").locator(".chg")).to_have_class(re.compile(r"\bup\b"))
    expect(chip(page, "NVDA").locator(".px")).to_have_text(f"{generated_price('NVDA'):,.2f}")
    expect(chip(page, "NVDA").locator(".name")).to_have_text("NVDA Corp")


def test_clicking_a_ticker_opens_its_page(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(page).to_have_url(re.compile(r"/ticker/MSFT$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("MSFT")
    expect(page.locator('[data-tab="portfolio"]')).to_have_attribute("aria-current", "page")


def test_add_ticker_persists_after_reload(page: Page, live_server):
    open_portfolio(page, live_server)
    add_ticker(page, "tsla")
    expect(chip(page, "TSLA")).to_be_visible()
    expect(chip(page, "TSLA").locator(".px")).to_have_text(f"{generated_price('TSLA'):,.2f}")
    expect(page.get_by_test_id("add-form")).to_be_hidden()
    expect(chips(page)).to_have_count(len(DEFAULT) + 1)
    expect(page.get_by_test_id("portfolio-count")).to_have_text(str(len(DEFAULT) + 1))

    page.reload()
    expect(chips(page).locator(".sym")).to_have_text(DEFAULT + ["TSLA"])


def test_remove_ticker_persists_after_reload(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "LLY").hover()
    page.get_by_role("button", name="Remove LLY").click()
    expect(chip(page, "LLY")).to_have_count(0)
    expect(page.get_by_test_id("portfolio-count")).to_have_text(str(len(DEFAULT) - 1))
    page.reload()
    expect(chips(page)).to_have_count(len(DEFAULT) - 1)
    expect(chip(page, "LLY")).to_have_count(0)


def test_add_rejects_invalid_duplicate_and_unknown_tickers(page: Page, live_server):
    open_portfolio(page, live_server)
    add_ticker(page, "1BAD")
    expect(page.get_by_test_id("add-error")).to_have_text("Enter a valid ticker symbol, like TSLA.")

    page.get_by_label("New ticker symbol").fill("aapl")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("AAPL is already in your portfolio.")

    page.get_by_label("New ticker symbol").fill("NOPEX")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("Couldn't find NOPEX.")
    expect(chips(page)).to_have_count(len(DEFAULT))


def test_add_form_can_be_cancelled(page: Page, live_server):
    open_portfolio(page, live_server)
    page.get_by_role("button", name="Add ticker").click()
    expect(page.get_by_test_id("add-form")).to_be_visible()
    page.get_by_label("New ticker symbol").press("Escape")
    expect(page.get_by_test_id("add-form")).to_be_hidden()


def test_front_page_features_a_top_story(page: Page, live_server):
    page.goto(live_server)
    featured = page.locator(".news-item.featured")
    expect(featured).to_have_count(1)
    expect(featured).to_contain_text("Stocks rally to record")
