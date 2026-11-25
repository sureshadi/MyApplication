"""Left "Sources" pane on the news tabs. `local_only` tests check the mocked headline counts exactly."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import no_horizontal_scroll

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]
local_only = pytest.mark.local_only


def source_link(page: Page, slug: str):
    return page.locator(f'[data-testid="source-link"][data-slug="{slug}"]')


def count_of(link) -> int:
    return int(link.locator(".source-count").inner_text())


def first_source_with_news(page: Page):
    """The first source in the pane (not "All sources") that has headlines: (slug, name, count)."""
    for link in page.locator('[data-testid="source-link"]:not([data-slug="all"])').all():
        if count_of(link) > 0:
            return link.get_attribute("data-slug"), link.locator(".source-name").inner_text().strip(), count_of(link)
    pytest.fail("no source in the pane has any headlines")


def test_pick_a_source_in_sidebar_filters_headlines(page: Page, live_server):
    page.goto(live_server)
    expect(source_link(page, "all")).to_have_attribute("aria-current", "page")
    slug, name, count = first_source_with_news(page)

    source_link(page, slug).click()
    expect(page).to_have_url(re.compile(rf"/\?source={slug}$"))
    expect(page.get_by_test_id("feed-heading")).to_have_text(f"Latest from {name}")
    expect(page.get_by_test_id("news-item")).to_have_count(count)
    expect(page.locator(".news-source")).to_have_text([name] * count)
    expect(source_link(page, slug)).to_have_attribute("aria-current", "page")
    expect(source_link(page, "all")).not_to_have_attribute("aria-current", "page")

    source_link(page, "all").click()
    expect(page.get_by_test_id("feed-heading")).to_have_text("Latest financial news")
    expect(source_link(page, "all")).to_have_attribute("aria-current", "page")


def test_sidebar_counts_match_the_headlines(page: Page, live_server):
    page.goto(live_server)
    total = count_of(source_link(page, "all"))
    expect(page.get_by_test_id("news-item")).to_have_count(total)
    per_source = [count_of(l) for l in page.locator('[data-testid="source-link"]:not([data-slug="all"])').all()]
    assert sum(per_source) == total


@local_only
def test_sidebar_shows_mocked_counts(page: Page, live_server):
    page.goto(live_server)
    expect(source_link(page, "all").locator(".source-count")).to_have_text("4")
    expect(source_link(page, "marketwatch").locator(".source-count")).to_have_text("2")
    expect(source_link(page, "broken").locator(".source-count")).to_have_text("0")
    source_link(page, "cnbc").click()
    expect(page.get_by_test_id("feed-heading")).to_have_text("Latest from CNBC")
    expect(page.locator(".news-source")).to_have_text(["CNBC", "CNBC"])


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
    slug, _, count = first_source_with_news(page)
    source_link(page, slug).click()
    expect(page.get_by_test_id("news-item")).to_have_count(count)
    assert no_horizontal_scroll(page)
