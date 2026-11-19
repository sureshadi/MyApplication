"""Google-style suggestions under the ticker search box."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def box(page: Page):
    return page.get_by_role("combobox", name="Ticker symbol")


def test_typing_part_of_a_ticker_shows_suggestions(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("nv", delay=40)
    options = page.get_by_role("option")
    expect(options.first).to_contain_text("NVDA")
    expect(options.first).to_contain_text("NVIDIA Corporation")
    expect(box(page)).to_have_attribute("aria-expanded", "true")


def test_click_a_suggestion_opens_the_ticker(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("micro", delay=40)
    page.get_by_role("option").filter(has_text="Microsoft").click()
    expect(page).to_have_url(re.compile(r"/ticker/MSFT$"))


def test_keyboard_arrows_and_enter(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("a", delay=40)
    expect(page.get_by_role("option").first).to_contain_text("AAPL")
    box(page).press("ArrowDown")
    box(page).press("ArrowDown")
    expect(page.get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
    box(page).press("Enter")
    expect(page).to_have_url(re.compile(r"/ticker/AMZN$"))


def test_company_name_then_enter_opens_top_match(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("apple", delay=40)
    expect(page.get_by_role("option").first).to_contain_text("AAPL")
    box(page).press("Enter")
    expect(page).to_have_url(re.compile(r"/ticker/AAPL$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("AAPL")


def test_less_common_tickers_come_from_yahoo_search(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("rivian", delay=40)
    expect(page.get_by_role("option")).to_have_count(1)
    expect(page.get_by_role("option").first).to_contain_text("Rivian Automotive")


def test_escape_closes_and_unknown_shows_message(page: Page, live_server):
    page.goto(live_server)
    box(page).press_sequentially("zzzzq", delay=40)
    expect(page.get_by_test_id("suggestions")).to_contain_text("No matching tickers")
    box(page).press("Escape")
    expect(page.get_by_test_id("suggestions")).to_be_hidden()


def test_typed_symbol_still_looks_up_directly(page: Page, live_server):
    page.goto(live_server)
    box(page).fill("aapl")
    page.get_by_role("button", name="Look up").click()
    expect(page).to_have_url(re.compile(r"/ticker/AAPL$"))


def test_suggestions_fit_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server)
    box(page).press_sequentially("ap", delay=40)
    expect(page.get_by_role("option").first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
