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


def test_technology_and_health_sections_sit_above_financial_news(page: Page, live_server):
    page.goto(live_server)
    tech = page.get_by_role("region", name="Technology")
    health = page.get_by_role("region", name="Health")
    expect(tech.get_by_test_id("topic-item")).to_have_count(3)
    expect(health.get_by_test_id("topic-item")).to_have_count(2)
    expect(tech.get_by_test_id("topic-item").first).to_contain_text("Chipmakers race to build faster AI accelerators")
    finance_y = page.get_by_test_id("feed-heading").bounding_box()["y"]
    assert tech.bounding_box()["y"] < finance_y
    assert health.bounding_box()["y"] < finance_y


def test_topic_sections_fit_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server)
    expect(page.get_by_role("region", name="Technology")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
