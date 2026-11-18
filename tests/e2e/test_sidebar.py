import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def source_link(page: Page, slug: str):
    return page.locator(f'[data-testid="source-link"][data-slug="{slug}"]')


def test_pick_a_source_in_sidebar_filters_headlines(page: Page, live_server):
    page.goto(live_server)
    expect(page.get_by_test_id("news-item")).to_have_count(4)
    expect(source_link(page, "all")).to_have_attribute("aria-current", "page")

    source_link(page, "cnbc").click()
    expect(page).to_have_url(re.compile(r"/\?source=cnbc$"))
    expect(page.get_by_test_id("feed-heading")).to_have_text("Latest from CNBC")
    expect(page.get_by_test_id("news-item")).to_have_count(2)
    expect(page.locator(".news-source")).to_have_text(["CNBC", "CNBC"])
    expect(source_link(page, "cnbc")).to_have_attribute("aria-current", "page")
    expect(source_link(page, "all")).not_to_have_attribute("aria-current", "page")

    source_link(page, "all").click()
    expect(page.get_by_test_id("feed-heading")).to_have_text("Latest financial news")
    expect(page.get_by_test_id("news-item")).to_have_count(4)


def test_sidebar_shows_counts(page: Page, live_server):
    page.goto(live_server)
    expect(source_link(page, "all").locator(".source-count")).to_have_text("4")
    expect(source_link(page, "marketwatch").locator(".source-count")).to_have_text("2")
    expect(source_link(page, "broken").locator(".source-count")).to_have_text("0")


def test_sidebar_is_beside_news_on_desktop(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_server)
    sidebar = page.get_by_test_id("source-sidebar").bounding_box()
    feed = page.get_by_test_id("news-list").bounding_box()
    assert sidebar["x"] + sidebar["width"] <= feed["x"]


def test_sidebar_becomes_pill_row_on_phone(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server)
    sidebar = page.get_by_test_id("source-sidebar").bounding_box()
    feed = page.get_by_test_id("news-list").bounding_box()
    assert sidebar["y"] + sidebar["height"] <= feed["y"]
    source_link(page, "marketwatch").click()
    expect(page.get_by_test_id("news-item")).to_have_count(2)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
