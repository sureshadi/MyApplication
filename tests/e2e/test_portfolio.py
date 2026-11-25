"""Portfolio tab: every ticker shows at once with live prices; add and remove are saved in this browser.

These also run against the live site (BASE_URL), signed in with PORTFOLIO_USER/PORTFOLIO_PASSWORD. The tickers
are kept in the browser's localStorage and each test gets a fresh browser, so adding or removing tickers here
never changes a real user's portfolio. `local_only` tests check the mocked prices exactly."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.conftest import generated_price
from tests.e2e.conftest import PERCENT, PRICE, REMOTE, no_horizontal_scroll

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]
local_only = pytest.mark.local_only

DEFAULT = ["AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT"]


def default_tickers(page: Page) -> list[str]:
    """The site's default tickers (the WATCHLIST setting), as the page states them."""
    return page.get_by_test_id("portfolio").get_attribute("data-default").split(",")


def chips(page: Page):
    return page.get_by_test_id("ticker-chip")


def chip(page: Page, symbol: str):
    return page.locator(f'[data-testid="ticker-chip"][data-symbol="{symbol}"]')


def open_portfolio(page: Page, live_server: str):
    page.goto(live_server)
    page.locator('[data-testid="tab"][data-tab="portfolio"]').click()  # not a headline that says "Portfolio"
    expect(page).to_have_url(re.compile(r"/portfolio$"))


def add_ticker(page: Page, symbol: str):
    page.get_by_role("button", name="Add ticker").click()
    page.get_by_label("New ticker symbol").fill(symbol)
    page.get_by_role("button", name="Add", exact=True).click()


@pytest.mark.parametrize("width", [1280, 375])
def test_clicking_my_portfolio_shows_every_ticker(page: Page, live_server, width):
    page.set_viewport_size({"width": width, "height": 900})
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="Portfolio")).to_be_visible()
    tickers = default_tickers(page)
    expect(chips(page)).to_have_count(len(tickers))
    expect(chips(page).locator(".sym")).to_have_text(tickers)
    # Every ticker is laid out on screen (wrapping grid), none hidden in a sideways scroller.
    for symbol in tickers:
        chip(page, symbol).scroll_into_view_if_needed()
        expect(chip(page, symbol)).to_be_in_viewport()
    assert no_horizontal_scroll(page)


@local_only
def test_default_tickers_are_the_configured_ones(page: Page, live_server):
    open_portfolio(page, live_server)
    assert default_tickers(page) == DEFAULT


def test_every_card_shows_a_price_and_change(page: Page, live_server):
    open_portfolio(page, live_server)
    for symbol in default_tickers(page):
        expect(chip(page, symbol).locator(".px")).to_have_text(re.compile(PRICE))
        expect(chip(page, symbol).locator(".name")).not_to_be_empty()
        # By default the badge is today's change (1D on the period picker).
        badge = chip(page, symbol).locator(".chg")
        expect(badge).to_have_text(re.compile(PERCENT))
        expect(badge).to_have_class(re.compile(r"\b(up|down|flat)\b"))


@local_only
def test_portfolio_shows_mocked_prices(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(chip(page, "AAPL").locator(".px")).to_have_text("232.50")
    # By default the badge is today's change (1D on the period picker).
    expect(chip(page, "AAPL").locator(".chg")).to_have_text("+1.09%")
    expect(chip(page, "AAPL").locator(".chg")).to_have_class(re.compile(r"\bup\b"))
    expect(chip(page, "NVDA").locator(".px")).to_have_text(f"{generated_price('NVDA'):,.2f}")
    expect(chip(page, "NVDA").locator(".name")).to_have_text("NVDA Corp")


def test_ticker_side_panel_links_to_its_full_page(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    page.get_by_test_id("panel-more").click()
    expect(page).to_have_url(re.compile(r"/ticker/MSFT$"))
    expect(page.get_by_test_id("quote-symbol")).to_have_text("MSFT")
    expect(page.locator('[data-tab="portfolio"]')).to_have_attribute("aria-current", "page")


def test_add_ticker_persists_after_reload(page: Page, live_server):
    open_portfolio(page, live_server)
    tickers = default_tickers(page)
    add_ticker(page, "tsla")
    expect(chip(page, "TSLA")).to_be_visible()
    expect(chip(page, "TSLA").locator(".px")).to_have_text(re.compile(PRICE))
    if not REMOTE:
        expect(chip(page, "TSLA").locator(".px")).to_have_text(f"{generated_price('TSLA'):,.2f}")
    expect(page.get_by_test_id("add-form")).to_be_hidden()
    expect(chips(page)).to_have_count(len(tickers) + 1)
    expect(page.get_by_test_id("portfolio-count")).to_have_text(str(len(tickers) + 1))

    page.reload()
    expect(chips(page).locator(".sym")).to_have_text(tickers + ["TSLA"])


def test_remove_ticker_persists_after_reload(page: Page, live_server):
    open_portfolio(page, live_server)
    tickers = default_tickers(page)
    gone = tickers[-1]
    chip(page, gone).hover()
    page.get_by_role("button", name=f"Remove {gone}").click()
    expect(chip(page, gone)).to_have_count(0)
    expect(page.get_by_test_id("portfolio-count")).to_have_text(str(len(tickers) - 1))
    page.reload()
    expect(chips(page)).to_have_count(len(tickers) - 1)
    expect(chip(page, gone)).to_have_count(0)


def test_add_rejects_invalid_duplicate_and_unknown_tickers(page: Page, live_server):
    open_portfolio(page, live_server)
    tickers = default_tickers(page)
    add_ticker(page, "1BAD")
    expect(page.get_by_test_id("add-error")).to_have_text("Enter a valid ticker symbol, like TSLA.")

    page.get_by_label("New ticker symbol").fill("aapl")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("AAPL is already in your portfolio.")

    # NOPE... symbols are unknown in the mocks; NOPEXQZ isn't a real ticker either.
    page.get_by_label("New ticker symbol").fill("NOPEXQZ")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("add-error")).to_have_text("Couldn't find NOPEXQZ.")
    expect(chips(page)).to_have_count(len(tickers))


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
    expect(featured).not_to_be_empty()
    # The top story is the newest headline.
    expect(page.get_by_test_id("news-item").first).to_have_class(re.compile(r"\bfeatured\b"))
    if not REMOTE:
        expect(featured).to_contain_text("Stocks rally to record")


def add_box(page: Page):
    return page.get_by_role("combobox", name="New ticker symbol")


def test_add_box_shows_suggestions_and_click_adds(page: Page, live_server):
    open_portfolio(page, live_server)
    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("tes", delay=40)
    option = page.get_by_test_id("add-suggestions").get_by_role("option").first
    expect(option).to_contain_text("TSLA")
    expect(option).to_contain_text("Tesla, Inc.")
    option.click()
    expect(chip(page, "TSLA")).to_be_visible()
    expect(chip(page, "TSLA").locator(".px")).to_have_text(re.compile(PRICE))
    expect(page.get_by_test_id("add-form")).to_be_hidden()


def test_add_box_keyboard_and_company_name(page: Page, live_server):
    open_portfolio(page, live_server)
    tickers = default_tickers(page)
    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("netflix", delay=40)
    expect(page.get_by_test_id("add-suggestions").get_by_role("option").first).to_contain_text("NFLX")
    add_box(page).press("Enter")  # company name + Enter adds the top match
    expect(chip(page, "NFLX")).to_be_visible()

    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("micro", delay=40)
    expect(page.get_by_test_id("add-suggestions").get_by_role("option").nth(1)).to_contain_text("AMD")
    add_box(page).press("ArrowDown")
    add_box(page).press("ArrowDown")
    add_box(page).press("Enter")
    expect(chip(page, "AMD")).to_be_visible()
    expect(chips(page)).to_have_count(len(tickers) + 2)


def test_add_box_escape_closes_list_first_then_form(page: Page, live_server):
    open_portfolio(page, live_server)
    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("ap", delay=40)
    expect(page.get_by_test_id("add-suggestions")).to_be_visible()
    add_box(page).press("Escape")
    expect(page.get_by_test_id("add-suggestions")).to_be_hidden()
    expect(page.get_by_test_id("add-form")).to_be_visible()
    add_box(page).press("Escape")
    expect(page.get_by_test_id("add-form")).to_be_hidden()


def test_add_box_suggestion_for_ticker_already_owned_shows_message(page: Page, live_server):
    open_portfolio(page, live_server)
    tickers = default_tickers(page)
    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("apple", delay=40)
    page.get_by_test_id("add-suggestions").get_by_role("option").first.click()
    expect(page.get_by_test_id("add-error")).to_have_text("AAPL is already in your portfolio.")
    expect(chips(page)).to_have_count(len(tickers))


def test_add_box_suggestions_fit_on_mobile(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    open_portfolio(page, live_server)
    page.get_by_role("button", name="Add ticker").click()
    add_box(page).press_sequentially("app", delay=40)
    list_box = page.get_by_test_id("add-suggestions")
    expect(list_box.get_by_role("option").first).to_be_visible()
    box = list_box.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    assert no_horizontal_scroll(page)
