"""Portfolio: clicking a ticker opens a side panel with its top 3 news, and market research shows
one tab per company (with a risk dot) and one company's analysis at a time, risks first.

These also run against the live site (BASE_URL) with real SEC filings and news: there they check the panel,
tabs and layout, not exact headlines or numbers. `local_only` tests check the mocked data exactly."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import REMOTE, no_horizontal_scroll

pytestmark = [pytest.mark.e2e, pytest.mark.remote_safe]
local_only = pytest.mark.local_only

LEVELS = re.compile(r"^(hi|md|lo|ok)$")


def open_portfolio(page: Page, live_server: str, tickers=None):
    if tickers is not None:
        page.add_init_script(f"localStorage.setItem('mh.watchlist.v1', '{json.dumps(tickers)}')")
    page.goto(f"{live_server}/portfolio")


def chip(page: Page, symbol: str):
    return page.locator(f'[data-testid="ticker-chip"][data-symbol="{symbol}"]')


def tab(page: Page, symbol: str):
    return page.locator(f'[data-testid="research-tab"][data-symbol="{symbol}"]')


def research(page: Page):
    return page.get_by_test_id("research-panel")


def panel(page: Page):
    return page.get_by_test_id("news-panel")


def panel_box(page: Page) -> dict:
    """Panel position once its slide-in animation has finished."""
    return panel(page).evaluate(
        "el => Promise.all(el.getAnimations().map(a => a.finished)).then(() => {"
        " const r = el.getBoundingClientRect(); return {x: r.x, width: r.width}; })"
    )


def expect_panel_news_loaded(page: Page, symbol: str):
    """Up to 3 headlines, each opening in a new tab, or a "no headlines" message (real news varies)."""
    news = page.get_by_test_id("panel-news")
    expect(news).to_have_text(re.compile(r"\S"))
    expect(news).not_to_contain_text("Loading")
    items = page.get_by_test_id("panel-news-item")
    if items.count():
        assert items.count() <= 3
        expect(items.first.get_by_role("link")).to_have_attribute("target", "_blank")
    else:
        expect(news).to_have_text(f"No recent headlines for {symbol}.")


def test_clicking_a_ticker_opens_side_panel_with_top_news(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "MSFT"])
    chip(page, "MSFT").get_by_role("link").click()
    expect(panel(page)).to_be_visible()
    expect(page).to_have_url(re.compile(r"/portfolio$"))  # stays on the page
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect(page.get_by_test_id("news-panel-name")).not_to_be_empty()
    expect_panel_news_loaded(page, "MSFT")
    expect(page.get_by_test_id("panel-more")).to_have_attribute("href", "/ticker/MSFT")
    expect(chip(page, "MSFT")).to_have_class(re.compile(r"\bis-open\b"))
    # The panel sits on the right side of the screen.
    box = panel_box(page)
    assert box["x"] + box["width"] == pytest.approx(page.viewport_size["width"], abs=1)


@local_only
def test_side_panel_shows_mocked_top_3_news(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(page.get_by_test_id("news-panel-name")).to_have_text("MSFT Corp")
    items = page.get_by_test_id("panel-news-item")
    expect(items).to_have_count(3)
    expect(items.first).to_contain_text("Microsoft cloud revenue tops estimates")


def test_panel_closes_with_escape_close_button_and_backdrop(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "MSFT"])
    chip(page, "AAPL").get_by_role("link").click()
    if not REMOTE:
        expect(page.get_by_test_id("panel-news-item")).to_have_count(2)  # AAPL only has 2 mocked headlines
    expect(panel(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect(panel(page)).to_be_hidden()

    chip(page, "AAPL").get_by_role("link").click()
    page.get_by_role("button", name="Close news panel").click()
    expect(panel(page)).to_be_hidden()

    chip(page, "AAPL").get_by_role("link").click()
    page.get_by_test_id("news-panel-backdrop").click(position={"x": 20, "y": 400})
    expect(panel(page)).to_be_hidden()


def test_panel_switches_between_tickers(page: Page, live_server):
    open_portfolio(page, live_server, ["MSFT", "NVDA"])
    chip(page, "MSFT").get_by_role("link").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect_panel_news_loaded(page, "MSFT")
    page.keyboard.press("Escape")
    chip(page, "NVDA").get_by_role("link").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("NVDA")
    expect(chip(page, "NVDA")).to_have_class(re.compile(r"\bis-open\b"))
    expect_panel_news_loaded(page, "NVDA")


@local_only
def test_panel_handles_no_news(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)
    page.keyboard.press("Escape")
    chip(page, "NVDA").get_by_role("link").click()
    expect(page.get_by_test_id("panel-news")).to_have_text("No recent headlines for NVDA.")


def test_one_tab_per_ticker_and_first_company_shown(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="Market research")).to_be_visible()
    tickers = page.get_by_test_id("portfolio").get_attribute("data-default").split(",")
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_count(len(tickers))
    expect(tabs.locator(".tab-sym")).to_have_text(tickers)
    expect(tab(page, tickers[0])).to_have_attribute("aria-selected", "true")
    expect(research(page)).to_have_attribute("data-symbol", tickers[0])
    expect(research(page).locator(".rp-name")).not_to_be_empty()
    # Only one company's analysis is on the page at a time.
    expect(page.get_by_test_id("research-headline")).to_have_count(1)
    if not REMOTE:
        expect(research(page).locator(".rp-name")).to_have_text("Apple Inc.")


def test_every_tab_gets_a_risk_dot(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "MSFT", "NVDA"])
    for symbol in ("AAPL", "MSFT", "NVDA"):
        expect(tab(page, symbol)).to_have_attribute("data-level", LEVELS)
        level = tab(page, symbol).get_attribute("data-level")
        expect(tab(page, symbol).locator(".tab-dot")).to_have_class(re.compile(rf"\bdot-{level}\b"))


@local_only
def test_tab_dots_show_each_companys_risk_level(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS", "ZZZZ"])
    expect(tab(page, "LOSS")).to_have_attribute("data-level", "hi")
    expect(tab(page, "AAPL")).to_have_attribute("data-level", "md")
    expect(tab(page, "ZZZZ")).to_have_attribute("data-level", "na")
    expect(tab(page, "LOSS").locator(".tab-dot")).to_have_class(re.compile(r"\bdot-hi\b"))


def test_risks_come_first_then_key_numbers(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL"])
    panel_el = research(page)
    expect(panel_el.get_by_test_id("research-kpis")).to_be_visible()
    expect(panel_el.get_by_test_id("risk-level")).to_have_text(re.compile(r"^(High risk|Watch|Low risk|No flags)$"))
    expect(panel_el.get_by_test_id("research-headline")).not_to_be_empty()
    order = panel_el.evaluate(
        "el => [...el.children].map(c => c.dataset.testid || c.className)"
    )
    assert order.index("research-risks") < order.index("research-kpis") < order.index("research-more")
    kpis = panel_el.get_by_test_id("kpi")
    expect(kpis.first.locator(".kpi-name")).to_have_text("Revenue")
    expect(kpis.first.locator(".kpi-value")).to_have_text(re.compile(r"^-?\$[\d.,]+[KMBT]?$"))
    expect(kpis.first.locator(".kpi-change")).to_contain_text("vs prior year")


@local_only
def test_risks_and_key_numbers_match_mocked_filings(page: Page, live_server):
    open_portfolio(page, live_server)
    panel_el = research(page)
    expect(panel_el.get_by_test_id("risk-level")).to_have_text("Watch")
    expect(panel_el.get_by_test_id("research-headline")).to_contain_text("revenue grew 8.5% year over year")
    expect(panel_el.get_by_test_id("risk").first).to_contain_text("Receivables growing faster than revenue")
    kpis = panel_el.get_by_test_id("kpi")
    expect(kpis.locator(".kpi-name")).to_have_text(["Revenue", "Operating margin", "Net income", "Free cash flow"])
    expect(kpis.first.locator(".kpi-value")).to_have_text("$102.00B")
    expect(kpis.first.locator(".kpi-change")).to_have_text("+8.5% vs prior year")
    expect(kpis.nth(1).locator(".kpi-change")).to_have_text("+1.0 pp vs prior year")


def test_clicking_a_tab_switches_company(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "MSFT"])
    expect(research(page)).to_have_attribute("data-symbol", "AAPL")
    tab(page, "MSFT").click()
    expect(tab(page, "MSFT")).to_have_attribute("aria-selected", "true")
    expect(tab(page, "AAPL")).to_have_attribute("aria-selected", "false")
    expect(research(page)).to_have_attribute("data-symbol", "MSFT")
    expect(research(page).get_by_test_id("research-headline")).to_have_count(1)


@local_only
def test_high_risk_company_shows_high_risk(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS"])
    tab(page, "LOSS").click()
    expect(research(page).get_by_test_id("risk-level")).to_have_text("High risk")
    expect(research(page).get_by_test_id("risk").first).to_have_attribute("data-severity", "high")


def test_arrow_keys_move_between_tabs(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "NVDA", "MSFT"])
    tab(page, "AAPL").focus()
    page.keyboard.press("ArrowRight")
    expect(tab(page, "NVDA")).to_be_focused()
    expect(research(page)).to_have_attribute("data-symbol", "NVDA")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")  # wraps around to the last tab
    expect(research(page)).to_have_attribute("data-symbol", "MSFT")


def test_show_reveals_all_fundamentals_drivers_guidance_and_sources(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL"])
    more = research(page).get_by_test_id("research-more")
    table = more.get_by_test_id("research-metrics")
    expect(table).to_be_hidden()
    more.locator("summary").click()
    expect(table).to_be_visible()
    expect(table.locator("thead th")).to_have_text(["Metric", "Prior year", "This period", "Change"])
    revenue = table.get_by_test_id("metric-row").first
    expect(revenue).to_contain_text(re.compile(r"ended .* · GAAP"))
    expect(revenue.locator("td")).to_have_count(3)
    if not REMOTE:
        expect(revenue).to_contain_text("Quarter ended Sep 27, 2026 · GAAP")
        # The earlier period is on the left, the latest on the right.
        expect(revenue.locator("td")).to_have_text(["$94.00B", "$102.00B", "+8.5%"])
    expect(more.get_by_test_id("research-drivers")).to_be_visible()
    expect(more.get_by_test_id("research-guidance")).to_be_visible()
    expect(more.locator(".rc-sources a").first).to_have_attribute("href", re.compile(r"sec\.gov/Archives"))


def test_top_news_button_opens_news_panel(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "MSFT"])
    tab(page, "MSFT").click()
    research(page).get_by_test_id("research-news").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect_panel_news_loaded(page, "MSFT")


@local_only
def test_company_without_sec_filings_shows_a_message(page: Page, live_server):
    open_portfolio(page, live_server, ["ZZZZ", "AAPL"])
    expect(research(page)).to_contain_text("No SEC filings found for ZZZZ")


def test_adding_and_removing_tickers_updates_tabs(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL"])
    expect(page.get_by_role("tab")).to_have_count(1)
    page.get_by_role("button", name="Add ticker").click()
    page.get_by_label("New ticker symbol").fill("TSLA")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(tab(page, "TSLA")).to_be_visible()
    tab(page, "TSLA").click()
    expect(research(page).get_by_test_id("research-kpis")).to_be_visible()
    chip(page, "TSLA").hover()
    page.get_by_role("button", name="Remove TSLA").click()
    expect(tab(page, "TSLA")).to_have_count(0)
    # The removed company was selected, so the first remaining one is shown.
    expect(research(page)).to_have_attribute("data-symbol", "AAPL")


def test_research_and_panel_fit_on_a_phone(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    open_portfolio(page, live_server, ["AAPL", "MSFT"])
    expect(research(page).get_by_test_id("research-kpis")).to_be_visible()
    assert no_horizontal_scroll(page)
    chip(page, "MSFT").get_by_role("link").click()
    box = panel_box(page)
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    expect_panel_news_loaded(page, "MSFT")
