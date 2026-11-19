import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_front_page_shows_headlines_newest_first(page: Page, live_server):
    page.goto(live_server)
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()
    items = page.get_by_test_id("news-item")
    expect(items).to_have_count(4)
    expect(items.first).to_contain_text("Stocks rally to record")
    expect(items.first).to_contain_text("MarketWatch")


def test_headlines_open_publisher_in_new_tab(page: Page, live_server):
    page.goto(live_server)
    link = page.get_by_role("link", name="Oil prices slip as supply concerns ease")
    expect(link).to_have_attribute("href", "https://www.cnbc.com/2026/11/18/oil-prices.html")
    expect(link).to_have_attribute("target", "_blank")


def test_search_ticker_shows_quote_and_related_news(page: Page, live_server):
    page.goto(live_server)
    page.get_by_label("Ticker symbol", exact=True).fill("aapl")
    page.get_by_role("button", name="Look up").click()
    expect(page).to_have_url(re.compile(r"/ticker/AAPL$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("AAPL")
    expect(page.get_by_test_id("quote-price")).to_have_text("232.50")
    expect(page.get_by_test_id("quote-change")).to_contain_text("+2.50")
    expect(page.get_by_test_id("quote-change")).to_have_class(re.compile(r"\bup\b"))
    expect(page.get_by_test_id("price-chart")).to_be_visible()
    expect(page.get_by_test_id("news-item").first).to_contain_text("Apple unveils new AI features")


def test_unknown_ticker_shows_not_found(page: Page, live_server):
    page.goto(f"{live_server}/ticker/ZZZZ")
    expect(page.get_by_role("heading", name="Symbol not found")).to_be_visible()
    page.get_by_role("link", name="Back to the latest news").click()
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()


def test_invalid_ticker_search_shows_message(page: Page, live_server):
    page.goto(live_server)
    page.get_by_label("Ticker symbol", exact=True).fill("1BAD")
    page.get_by_role("button", name="Look up").click()
    expect(page.get_by_test_id("invalid-symbol")).to_contain_text("is not a valid ticker symbol")


def test_mobile_layout_has_no_horizontal_scroll(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{live_server}/ticker/AAPL")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def tab(page: Page, slug: str):
    return page.locator(f'[data-testid="tab"][data-tab="{slug}"]')


def test_tabs_switch_the_page(page: Page, live_server):
    page.goto(live_server)
    expect(page.get_by_test_id("tab")).to_have_text(["Financial news", "Technology news", "Health news", "My Portfolio"])
    expect(tab(page, "financial")).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()

    page.get_by_role("link", name="Health news").click()
    expect(page).to_have_url(re.compile(r"/news/health$"))
    expect(page.get_by_role("heading", name="Latest health news")).to_be_visible()
    expect(tab(page, "health")).to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id("news-item")).to_have_count(2)
    expect(page.get_by_text("Stocks rally to record")).to_have_count(0)

    page.get_by_role("link", name="Technology news").click()
    expect(page.get_by_role("heading", name="Latest technology news")).to_be_visible()
    expect(page.get_by_test_id("news-item").first).to_contain_text("Chipmakers race to build faster AI accelerators")

    page.get_by_role("link", name="Financial news").click()
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()


def test_tabs_fit_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    for path in ("/", "/news/technology", "/news/health", "/portfolio"):
        page.goto(live_server + path)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), path
