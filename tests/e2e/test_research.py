"""My Portfolio: clicking a ticker opens a side panel with its top 3 news, and every company gets a
market research card with the risks at the top."""

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


def card(page: Page, symbol: str):
    return page.locator(f'[data-testid="research-card"][data-symbol="{symbol}"]')


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


def test_research_card_for_every_ticker_with_risks_at_the_top(page: Page, live_server):
    open_portfolio(page, live_server)
    expect(page.get_by_role("heading", name="Market research")).to_be_visible()
    expect(page.get_by_test_id("research-card")).to_have_count(8)
    aapl = card(page, "AAPL")
    expect(aapl.get_by_test_id("research-metrics")).to_be_visible()
    # Risks come first in the card body, before the headline and the metrics table.
    first_section = aapl.locator(".rc-body > *").first
    expect(first_section).to_have_attribute("data-testid", "research-risks")
    expect(aapl.get_by_test_id("risk").first).to_contain_text("Receivables growing faster than revenue")
    expect(aapl.get_by_test_id("research-headline")).to_contain_text("revenue grew 8.5% year over year")


def test_research_card_shows_key_metrics_table(page: Page, live_server):
    open_portfolio(page, live_server)
    table = card(page, "AAPL").get_by_test_id("research-metrics")
    expect(table.locator("thead th")).to_have_text(["Metric", "This period", "Prior year", "Change"])
    revenue = table.get_by_test_id("metric-row").first
    expect(revenue).to_contain_text("Revenue")
    expect(revenue).to_contain_text("Quarter ended Sep 27, 2026 · GAAP")
    expect(revenue.locator("td")).to_have_text(["$102.00B", "$94.00B", "+8.5%"])
    expect(table).to_contain_text("Gross margin")
    expect(table.get_by_test_id("metric-row").filter(has_text="Gross margin").locator("td").last).to_have_text("+1.0 pp")
    expect(card(page, "AAPL").get_by_test_id("research-guidance")).to_be_visible()
    expect(card(page, "AAPL").locator(".rc-sources a").first).to_have_attribute("href", re.compile(r"sec\.gov/Archives"))


def test_portfolio_risk_summary_lists_high_risks_first(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "LOSS"])
    summary = page.get_by_test_id("risk-summary")
    expect(summary).to_be_visible()
    first = summary.get_by_test_id("summary-risk").first
    expect(first).to_have_attribute("data-severity", "high")
    expect(first).to_contain_text("LOSS")
    # Clicking a ticker in the summary opens its news.
    first.get_by_role("button", name="LOSS").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("LOSS")


def test_clicking_research_symbol_opens_news_panel(page: Page, live_server):
    open_portfolio(page, live_server)
    card(page, "MSFT").get_by_test_id("research-symbol").click()
    expect(page.get_by_test_id("news-panel-symbol")).to_have_text("MSFT")
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)


def test_company_without_sec_filings_shows_a_message(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL", "ZZZZ"])
    expect(card(page, "ZZZZ")).to_contain_text("No SEC filings found for ZZZZ")


def test_adding_and_removing_tickers_updates_research(page: Page, live_server):
    open_portfolio(page, live_server, ["AAPL"])
    expect(page.get_by_test_id("research-card")).to_have_count(1)
    page.get_by_role("button", name="Add ticker").click()
    page.get_by_label("New ticker symbol").fill("TSLA")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(card(page, "TSLA").get_by_test_id("research-metrics")).to_be_visible()
    chip(page, "AAPL").hover()
    page.get_by_role("button", name="Remove AAPL").click()
    expect(card(page, "AAPL")).to_have_count(0)
    expect(page.get_by_test_id("research-card")).to_have_count(1)


def test_research_and_panel_fit_on_a_phone(page: Page, live_server):
    page.set_viewport_size({"width": 375, "height": 800})
    open_portfolio(page, live_server)
    expect(card(page, "AAPL").get_by_test_id("research-metrics")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    chip(page, "MSFT").get_by_role("link").click()
    box = panel_box(page)
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    expect(page.get_by_test_id("panel-news-item")).to_have_count(3)
