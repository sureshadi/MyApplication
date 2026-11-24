"""Portfolio: clicking a ticker opens a side panel with its top 3 news, and market research shows
one tab per company (with a risk dot) and one company's analysis at a time, risks first."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


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


def test_clicking_a_ticker_opens_side_panel_with_top_3_news(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(panel(page)).to_be_visible()
    expect(page).to_have_url(re.compile(r"/portfolio$"))  # stays on the page
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect(page.get_by_test_id("news-panel-name")).to_have_text("MSFT Corp")
    items = page.get_by_test_id("panel-news-item")
    expect(items).to_have_count(3)
    expect(items.first).to_contain_text("Microsoft cloud revenue tops estimates")
    expect(items.first.get_by_role("link")).to_have_attribute("target", "_blank")
    expect(page.get_by_test_id("panel-more")).to_have_attribute("href", "/ticker/MSFT")
    expect(chip(page, "MSFT")).to_have_class(re.compile(r"\bis-open\b"))
    # The panel sits on the right side of the screen.
    box = panel_box(page)
    assert box["x"] + box["width"] == pytest.approx(page.viewport_size["width"], abs=1)


def test_panel_closes_with_escape_close_button_and_backdrop(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "AAPL").get_by_role("link").click()
    expect(page.get_by_test_id("panel-news-item")).to_have_count(2)  # AAPL only has 2 headlines
    page.keyboard.press("Escape")
    expect(panel(page)).to_be_hidden()

    chip(page, "AAPL").get_by_role("link").click()
    page.get_by_role("button", name="Close news panel").click()
    expect(panel(page)).to_be_hidden()

    chip(page, "AAPL").get_by_role("link").click()
    page.get_by_test_id("news-panel-backdrop").click(position={"x": 20, "y": 400})
    expect(panel(page)).to_be_hidden()


def test_panel_switches_between_tickers_and_handles_no_news(page: Page, live_server):
    open_portfolio(page, live_server)
    chip(page, "MSFT").get_by_role("link").click()
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)
    page.keyboard.press("Escape")
    chip(page, "NVDA").get_by_role("link").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("NVDA")
    expect(page.get_by_test_id("panel-news")).to_have_text("No recent headlines for NVDA.")


def test_one_tab_per_ticker_and_first_company_shown(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="Market research")).to_be_visible()
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_count(8)
    expect(tabs.locator(".tab-sym")).to_have_text(["AAPL", "META", "NVDA", "AMAT", "AVGO", "LLY", "GOOGL", "MSFT"])
    expect(tab(page, "AAPL")).to_have_attribute("aria-selected", "true")
    expect(research(page)).to_have_attribute("data-symbol", "AAPL")
    expect(research(page).locator(".rp-name")).to_have_text("Apple Inc.")
    # Only one company's analysis is on the page at a time.
    expect(page.get_by_test_id("research-headline")).to_have_count(1)


def test_tab_dots_show_each_companys_risk_level(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS", "ZZZZ"])
    expect(tab(page, "LOSS")).to_have_attribute("data-level", "hi")
    expect(tab(page, "AAPL")).to_have_attribute("data-level", "md")
    expect(tab(page, "ZZZZ")).to_have_attribute("data-level", "na")
    expect(tab(page, "LOSS").locator(".tab-dot")).to_have_class(re.compile(r"\bdot-hi\b"))


def test_risks_come_first_then_key_numbers(page: Page, live_server):
    open_portfolio(page, live_server)
    panel_el = research(page)
    expect(panel_el.get_by_test_id("risk-level")).to_have_text("Watch")
    expect(panel_el.get_by_test_id("research-headline")).to_contain_text("revenue grew 8.5% year over year")
    order = panel_el.evaluate(
        "el => [...el.children].map(c => c.dataset.testid || c.className)"
    )
    assert order.index("research-risks") < order.index("research-kpis") < order.index("research-more")
    expect(panel_el.get_by_test_id("risk").first).to_contain_text("Receivables growing faster than revenue")
    kpis = panel_el.get_by_test_id("kpi")
    expect(kpis.locator(".kpi-name")).to_have_text(["Revenue", "Operating margin", "Net income", "Free cash flow"])
    expect(kpis.first.locator(".kpi-value")).to_have_text("$102.00B")
    expect(kpis.first.locator(".kpi-change")).to_have_text("+8.5% vs prior year")
    expect(kpis.nth(1).locator(".kpi-change")).to_have_text("+1.0 pp vs prior year")


def test_clicking_a_tab_switches_company(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS"])
    tab(page, "LOSS").click()
    expect(tab(page, "LOSS")).to_have_attribute("aria-selected", "true")
    expect(tab(page, "AAPL")).to_have_attribute("aria-selected", "false")
    expect(research(page).get_by_test_id("risk-level")).to_have_text("High risk")
    expect(research(page).get_by_test_id("risk").first).to_have_attribute("data-severity", "high")


def test_arrow_keys_move_between_tabs(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS", "MSFT"])
    tab(page, "AAPL").focus()
    page.keyboard.press("ArrowRight")
    expect(tab(page, "LOSS")).to_be_focused()
    expect(research(page)).to_have_attribute("data-symbol", "LOSS")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")  # wraps around to the last tab
    expect(research(page)).to_have_attribute("data-symbol", "MSFT")


def test_show_reveals_all_fundamentals_drivers_guidance_and_sources(page: Page, live_server):
    open_portfolio(page, live_server)
    more = research(page).get_by_test_id("research-more")
    table = more.get_by_test_id("research-metrics")
    expect(table).to_be_hidden()
    more.locator("summary").click()
    expect(table).to_be_visible()
    expect(table.locator("thead th")).to_have_text(["Metric", "Prior year", "This period", "Change"])
    revenue = table.get_by_test_id("metric-row").first
    expect(revenue).to_contain_text("Quarter ended Sep 27, 2026 · GAAP")
    # The earlier period is on the left, the latest on the right.
    expect(revenue.locator("td")).to_have_text(["$94.00B", "$102.00B", "+8.5%"])
    expect(more.get_by_test_id("research-drivers")).to_be_visible()
    expect(more.get_by_test_id("research-guidance")).to_be_visible()
    expect(more.locator(".rc-sources a").first).to_have_attribute("href", re.compile(r"sec\.gov/Archives"))


def test_top_news_button_opens_news_panel(page: Page, live_server):
    open_portfolio(page, live_server)
    tab(page, "MSFT").click()
    research(page).get_by_test_id("research-news").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)


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
    open_portfolio(page, live_server)
    expect(research(page).get_by_test_id("research-kpis")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    chip(page, "MSFT").get_by_role("link").click()
    box = panel_box(page)
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)
