"""The left source pane must stay perfectly still while the headlines scroll."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]


def _make_page_long(page: Page):
    # The sample data has only a few headlines (and live feeds vary); make the feed tall so the page can really scroll.
    page.evaluate("document.querySelector('.feed').style.minHeight = '4000px'")


def _top(page: Page, testid: str) -> float:
    return page.get_by_test_id(testid).bounding_box()["y"]


def _scroll_to(page: Page, y: int):
    page.evaluate(f"window.scrollTo(0, {y})")
    page.wait_for_function(f"Math.abs(window.scrollY - {y}) < 2 || window.scrollY + window.innerHeight >= document.body.scrollHeight - 2")


def _source_slugs(page: Page) -> list[str]:
    return page.locator('[data-testid="source-link"]').evaluate_all("els => els.map(e => e.dataset.slug)")


@pytest.mark.parametrize("width", [1440, 1280, 1000])
def test_sidebar_does_not_move_when_scrolling(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(live_server)
    _make_page_long(page)
    start_sidebar = _top(page, "source-sidebar")
    start_news = _top(page, "news-list")

    for y in (50, 150, 400, 1500, 100000):
        _scroll_to(page, y)
        assert abs(_top(page, "source-sidebar") - start_sidebar) < 1, f"sidebar moved after scrolling to {y}"

    assert _top(page, "news-list") < start_news - 1000  # the headlines did scroll


def test_sidebar_stays_below_header_and_fully_visible(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(live_server)
    _make_page_long(page)
    _scroll_to(page, 2000)
    header = page.locator(".site-header").bounding_box()
    sidebar = page.get_by_test_id("source-sidebar").bounding_box()
    assert sidebar["y"] >= header["y"] + header["height"]
    assert sidebar["y"] + sidebar["height"] <= 800
    expect(page.locator('[data-testid="source-link"][data-slug="all"]')).to_be_in_viewport()


def test_sidebar_still_works_after_scrolling(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(live_server)
    start = _top(page, "source-sidebar")
    _make_page_long(page)
    _scroll_to(page, 1500)
    link = page.locator('[data-testid="source-link"]:not([data-slug="all"])').first
    name = link.get_attribute("data-source")
    link.click()
    expect(page.get_by_test_id("feed-heading")).to_have_text(f"Latest from {name}")
    assert abs(_top(page, "source-sidebar") - start) < 1


def test_sidebar_position_matches_on_every_source(page: Page, live_server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(live_server)
    tops = []
    for slug in _source_slugs(page):
        page.goto(live_server + ("/" if slug == "all" else f"/?source={slug}"))
        tops.append(_top(page, "source-sidebar"))
    assert max(tops) - min(tops) < 1


def test_sidebar_scrolls_away_normally_on_phone(page: Page, live_server):
    # On phones the pane is a row of pills above the news, not a pinned column.
    page.set_viewport_size({"width": 375, "height": 700})
    page.goto(live_server)
    _make_page_long(page)
    start = _top(page, "source-sidebar")
    _scroll_to(page, 600)
    assert _top(page, "source-sidebar") < start - 500
