"""Portfolio period picker: 1D, 1M, 3M, 6M, 1Y, 2Y or 5Y sets the card badges and what the research compares with.

These also run against the live site (BASE_URL): there they check that the picker changes the badges, titles,
comparison text and table headers, not the exact numbers. `local_only` tests check the mocked numbers."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import PERCENT, PRICE, REMOTE, no_horizontal_scroll

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]
local_only = pytest.mark.local_only

# LOSS is a made-up company in the mocks whose share price only fell; the live site gets a real second ticker.
SECOND = "MSFT" if REMOTE else "LOSS"


def open_portfolio(page: Page, live_server: str, tickers=("AAPL", SECOND)):
    page.add_init_script(f"if (!sessionStorage.getItem('seeded')) {{ localStorage.setItem('mh.watchlist.v1', '{json.dumps(list(tickers))}'); sessionStorage.setItem('seeded', '1'); }}")
    page.goto(f"{live_server}/portfolio")


def option(page: Page, key: str):
    return page.locator(f'[data-testid="period-option"][data-period="{key}"]')


def badge(page: Page, symbol: str):
    return page.locator(f'[data-testid="ticker-chip"][data-symbol="{symbol}"] .chg')


def research(page: Page):
    return page.get_by_test_id("research-panel")


def show_table(page: Page):
    more = research(page).get_by_test_id("research-more")
    more.locator("summary").click()
    return more.get_by_test_id("research-metrics")


def test_today_is_the_default(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="Portfolio", exact=True)).to_be_visible()
    expect(page.get_by_test_id("period-option")).to_have_text(["1D", "1M", "3M", "6M", "1Y", "2Y", "5Y"])
    expect(option(page, "1D")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("period-name")).to_have_text("1 day")
    # Today's change, as on a quote screen.
    expect(badge(page, "AAPL")).to_have_text(re.compile(PERCENT))
    expect(badge(page, "AAPL")).to_have_attribute("title", "Change today")
    compare = research(page).get_by_test_id("research-compare")
    expect(compare).to_contain_text("a year earlier")
    expect(compare).to_contain_text("today's change")


@local_only
def test_today_shows_the_mocked_price_and_change(page: Page, live_server):
    open_portfolio(page, live_server)
    card = page.locator('[data-testid="ticker-chip"][data-symbol="AAPL"]')
    expect(card.locator(".px")).to_have_text("232.50")
    expect(badge(page, "AAPL")).to_have_text("+1.09%")


def test_badges_follow_the_period(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(badge(page, "AAPL")).to_have_text(re.compile(PERCENT))
    today = badge(page, "AAPL").inner_text()
    option(page, "5Y").click()
    expect(option(page, "5Y")).to_have_attribute("aria-checked", "true")
    expect(option(page, "1D")).to_have_attribute("aria-checked", "false")
    expect(page.get_by_test_id("period-name")).to_have_text("5 years")
    expect(badge(page, "AAPL")).to_have_attribute("title", "Price change over 5 years")
    expect(badge(page, "AAPL")).to_have_text(re.compile(PERCENT))
    expect(badge(page, "AAPL")).not_to_have_text(today)
    for symbol in ("AAPL", SECOND):
        expect(badge(page, symbol)).to_have_class(re.compile(r"\b(up|down|flat)\b"))
    option(page, "1M").click()
    expect(badge(page, "AAPL")).to_have_attribute("title", "Price change over 1 month")
    expect(badge(page, "AAPL")).to_have_text(re.compile(PERCENT))


@local_only
def test_mocked_badges_over_five_years(page: Page, live_server):
    open_portfolio(page, live_server)
    option(page, "5Y").click()
    expect(badge(page, "AAPL")).not_to_have_text("+1.09%")
    expect(badge(page, "AAPL")).to_have_class(re.compile(r"\bup\b"))
    # LOSS traded higher in the past, so it is down over every period.
    expect(badge(page, "LOSS")).to_have_text(re.compile(r"^-\d+\.\d\d%$"))
    expect(badge(page, "LOSS")).to_have_class(re.compile(r"\bdown\b"))


def test_research_compares_with_the_chosen_period(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(research(page).get_by_test_id("research-kpis")).to_be_visible()
    option(page, "3M").click()
    panel = research(page)
    expect(panel.get_by_test_id("research-compare")).to_contain_text("a quarter earlier")
    expect(panel.get_by_test_id("kpi").first.locator(".kpi-change")).to_contain_text("vs prior quarter")
    table = show_table(page)
    expect(table.locator("thead th")).to_have_text(["Metric", "Prior quarter", "This period", "Change"])
    expect(table.get_by_test_id("metric-row").first.locator("td")).to_have_count(3)

    option(page, "5Y").click()
    expect(table.locator("thead th").nth(1)).to_have_text("5 years ago")
    expect(research(page).get_by_test_id("research-compare")).to_contain_text("5 years")


@local_only
def test_research_shows_mocked_numbers_for_the_period(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(research(page).get_by_test_id("research-kpis")).to_be_visible()
    option(page, "3M").click()
    panel = research(page)
    expect(panel.get_by_test_id("research-headline")).to_contain_text("quarter over quarter")
    expect(panel.get_by_test_id("kpi").first.locator(".kpi-change")).to_have_text("+5.3% vs prior quarter")
    table = show_table(page)
    expect(table.get_by_test_id("metric-row").first.locator("td")).to_have_text(["$96.90B", "$102.00B", "+5.3%"])
    option(page, "5Y").click()
    expect(research(page).get_by_test_id("metric-row").first.locator("td")).to_have_text(["$56.40B", "$102.00B", "+80.9%"])


def test_one_month_explains_that_filings_are_quarterly(page: Page, live_server):
    open_portfolio(page, live_server)
    option(page, "1M").click()
    expect(research(page).get_by_test_id("research-compare")).to_contain_text("Companies report every quarter")
    option(page, "1D").click()
    expect(badge(page, "AAPL")).to_have_attribute("title", "Change today")
    expect(research(page).get_by_test_id("research-compare")).to_contain_text("today's change")


@local_only
def test_share_price_risk_uses_the_period(page: Page, live_server):
    open_portfolio(page, live_server, ("LOSS",))
    option(page, "5Y").click()
    risks = research(page).get_by_test_id("risk")
    expect(risks.filter(has_text="Share price fell sharply")).to_contain_text("over the last 5 years")


def test_choice_is_saved_and_arrow_keys_move_it(page: Page, live_server):
    open_portfolio(page, live_server)
    option(page, "6M").click()
    page.reload()
    expect(option(page, "6M")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("period-name")).to_have_text("6 months")
    option(page, "6M").focus()
    page.keyboard.press("ArrowRight")
    expect(option(page, "1Y")).to_be_focused()
    expect(option(page, "1Y")).to_have_attribute("aria-checked", "true")


def test_picker_fits_on_a_phone(page: Page, live_server):
    page.set_viewport_size({"width": 390, "height": 844})
    open_portfolio(page, live_server)
    expect(page.get_by_test_id("period-picker")).to_be_in_viewport()
    assert no_horizontal_scroll(page)


def test_price_still_shows_when_quotes_fail(page: Page, live_server):
    # If the quote request fails, the card takes the current price and changes from the price history.
    page.route("**/api/quotes*", lambda route: route.fulfill(status=503, body="{}"))
    open_portfolio(page, live_server)
    card = page.locator('[data-testid="ticker-chip"][data-symbol="AAPL"]')
    expect(card.locator(".px")).to_have_text(re.compile(PRICE))
    expect(badge(page, "AAPL")).to_have_text(re.compile(PERCENT))
    if not REMOTE:
        expect(card.locator(".px")).to_have_text("232.50")
