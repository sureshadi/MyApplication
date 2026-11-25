"""News tabs, source pane, ticker search and ticker page.

Tests marked `local_only` check the mocked headlines and prices exactly; the rest check layout and
behaviour and also run against the live site (BASE_URL)."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import PRICE, no_horizontal_scroll

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]
local_only = pytest.mark.local_only


def tab(page: Page, slug: str):
    return page.locator(f'[data-testid="tab"][data-tab="{slug}"]')


# ---------- Front page ----------

def test_front_page_lists_headlines_newest_first(page: Page, live_server):
    page.goto(live_server)
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()
    items = page.get_by_test_id("news-item")
    expect(items.first).to_be_visible()
    # Every headline names its source and has a title link.
    for i in range(min(items.count(), 10)):
        expect(items.nth(i).locator(".news-source")).not_to_be_empty()
        expect(items.nth(i).get_by_role("link").first).not_to_be_empty()
    times = page.locator('[data-testid="news-item"] time[datetime]').evaluate_all(
        "els => els.map(e => Date.parse(e.getAttribute('datetime')))"
    )
    assert times == sorted(times, reverse=True), "headlines are not newest first"


@local_only
def test_front_page_shows_mocked_headlines(page: Page, live_server):
    page.goto(live_server)
    items = page.get_by_test_id("news-item")
    expect(items).to_have_count(4)
    expect(items.first).to_contain_text("Stocks rally to record")
    expect(items.first).to_contain_text("MarketWatch")


def test_headlines_open_publisher_in_new_tab(page: Page, live_server):
    page.goto(live_server)
    links = page.locator('[data-testid="news-item"] a[href^="http"]')
    expect(links.first).to_be_visible()
    for i in range(min(links.count(), 10)):
        expect(links.nth(i)).to_have_attribute("target", "_blank")
        assert not links.nth(i).get_attribute("href").startswith(live_server)


@local_only
def test_headline_links_to_the_mocked_article(page: Page, live_server):
    page.goto(live_server)
    link = page.get_by_role("link", name="Oil prices slip as supply concerns ease")
    expect(link).to_have_attribute("href", "https://www.cnbc.com/2026/11/18/oil-prices.html")


# ---------- Ticker search and page ----------

def test_search_ticker_shows_quote_and_chart(page: Page, live_server):
    page.goto(live_server)
    page.get_by_label("Ticker symbol", exact=True).fill("aapl")
    page.get_by_role("button", name="Look up").click()
    expect(page).to_have_url(re.compile(r"/ticker/AAPL$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("AAPL")
    expect(page.get_by_test_id("quote-price")).to_have_text(re.compile(PRICE))
    change = page.get_by_test_id("quote-change")
    expect(change).to_have_text(re.compile(r"[+-]?\d"))
    expect(change).to_have_class(re.compile(r"\b(up|down|flat)\b"))
    expect(page.get_by_test_id("price-chart")).to_be_visible()


@local_only
def test_ticker_page_shows_mocked_quote_and_news(page: Page, live_server):
    page.goto(f"{live_server}/ticker/AAPL")
    expect(page.get_by_test_id("quote-price")).to_have_text("232.50")
    expect(page.get_by_test_id("quote-change")).to_contain_text("+2.50")
    expect(page.get_by_test_id("quote-change")).to_have_class(re.compile(r"\bup\b"))
    expect(page.get_by_test_id("news-item").first).to_contain_text("Apple unveils new AI features")


@local_only
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
    expect(page.get_by_test_id("quote-symbol")).to_be_visible()
    assert no_horizontal_scroll(page)


# ---------- Tabs ----------

def test_tabs_switch_the_page(page: Page, live_server):
    page.goto(live_server)
    expect(page.get_by_test_id("tab")).to_have_text(["Financial news", "Technology news", "Health news", "Portfolio"])
    expect(tab(page, "financial")).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()

    page.get_by_role("link", name="Health news").click()
    expect(page).to_have_url(re.compile(r"/news/health$"))
    expect(page.get_by_role("heading", name="Latest health news")).to_be_visible()
    expect(tab(page, "health")).to_have_attribute("aria-current", "page")
    expect(tab(page, "financial")).not_to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id("news-item").first).to_be_visible()

    page.get_by_role("link", name="Technology news").click()
    expect(page).to_have_url(re.compile(r"/news/technology$"))
    expect(page.get_by_role("heading", name="Latest technology news")).to_be_visible()
    expect(tab(page, "technology")).to_have_attribute("aria-current", "page")
    expect(page.get_by_test_id("news-item").first).to_be_visible()

    page.get_by_role("link", name="Portfolio").click()
    expect(page).to_have_url(re.compile(r"/portfolio$"))
    expect(tab(page, "portfolio")).to_have_attribute("aria-current", "page")

    page.get_by_role("link", name="Financial news").click()
    expect(page.get_by_role("heading", name="Latest financial news")).to_be_visible()


@local_only
def test_topic_tabs_show_their_own_mocked_news(page: Page, live_server):
    page.goto(f"{live_server}/news/health")
    expect(page.get_by_test_id("news-item")).to_have_count(2)
    expect(page.get_by_text("Stocks rally to record")).to_have_count(0)
    page.goto(f"{live_server}/news/technology")
    expect(page.get_by_test_id("news-item").first).to_contain_text("Chipmakers race to build faster AI accelerators")


def test_tabs_fit_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    for path in ("/", "/news/technology", "/news/health", "/portfolio"):
        page.goto(live_server + path)
        expect(page.get_by_test_id("tab").first).to_be_visible()
        assert no_horizontal_scroll(page), path


def test_topic_tabs_have_a_sources_pane(page: Page, live_server):
    page.goto(f"{live_server}/news/health")
    sidebar = page.get_by_test_id("source-sidebar")
    expect(sidebar).to_be_visible()
    links = sidebar.get_by_test_id("source-link")
    expect(links.first).to_have_attribute("data-slug", "all")
    expect(links.first).to_have_attribute("aria-current", "page")
    # Pick the first source that has headlines.
    source = sidebar.locator('[data-testid="source-link"]:not([data-slug="all"])').filter(
        has_not=page.locator('.source-count:text-is("0")')
    ).first
    slug, name = source.get_attribute("data-slug"), source.locator(".source-name").inner_text().strip()
    source.click()
    expect(page).to_have_url(re.compile(rf"/news/health\?source={slug}$"))
    expect(page.get_by_role("heading", name=f"Health news from {name}")).to_be_visible()
    expect(page.get_by_test_id("news-item").first).to_be_visible()
    expect(page.locator('[data-tab="health"]')).to_have_attribute("aria-current", "page")


@local_only
def test_topic_sources_pane_lists_mocked_sources(page: Page, live_server):
    page.goto(f"{live_server}/news/health")
    sidebar = page.get_by_test_id("source-sidebar")
    expect(sidebar.get_by_test_id("source-link")).to_have_count(3)  # All sources + HealthDaily + Broken
    sidebar.get_by_role("link", name=re.compile("HealthDaily")).click()
    expect(page.get_by_test_id("news-item")).to_have_count(2)
