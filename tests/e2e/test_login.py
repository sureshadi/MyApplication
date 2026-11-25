"""Playwright UI tests for the Portfolio sign-in: signing in, wrong details, empty fields,
redirects, signing out, the lockout after too many tries and staying signed in."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from app import auth
from tests.conftest import TEST_PASSWORD, TEST_USER
from tests.e2e.pages.login_page import LoginPage

pytestmark = pytest.mark.e2e

PORTFOLIO_URL = re.compile(r"/portfolio$")
LOGIN_URL = re.compile(r"/login(\?|$)")


@pytest.fixture(autouse=True)
def _fresh_throttle(live_app):
    """Each test starts with no failed attempts, so the lockout test can't affect the others."""
    live_app.state.login_throttle._failures.clear()
    yield
    live_app.state.login_throttle._failures.clear()


@pytest.fixture
def login(anon_page: Page, live_server: str) -> LoginPage:
    return LoginPage(anon_page, live_server)


def session_cookie(page: Page) -> dict | None:
    return next((c for c in page.context.cookies() if c["name"] == auth.COOKIE_NAME), None)


# ---------- Redirect to sign-in ----------

def test_portfolio_tab_redirects_to_sign_in(login: LoginPage, live_server):
    login.page.goto(f"{live_server}/")
    login.page.locator("[data-tab=portfolio]").click()
    expect(login.page).to_have_url(f"{live_server}/login?next=/portfolio")
    expect(login.heading).to_be_visible()
    expect(login.page.locator("[data-tab=portfolio]")).to_have_attribute("aria-current", "page")


def test_direct_portfolio_link_redirects_then_returns(login: LoginPage, live_server):
    login.page.goto(f"{live_server}/portfolio")
    expect(login.page).to_have_url(LOGIN_URL)
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)


def test_sign_in_page_never_sends_you_off_site(login: LoginPage, live_server):
    login.open(next_path="https://evil.example/")
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(f"{live_server}/portfolio")


# ---------- Correct sign-in ----------

def test_correct_username_and_password_open_portfolio(login: LoginPage):
    login.open(next_path="/portfolio")
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)
    expect(login.page.get_by_role("heading", name="Portfolio", exact=True)).to_be_visible()
    expect(login.page.get_by_test_id("ticker-chip")).to_have_count(8)
    expect(login.page.get_by_test_id("research-tabs").get_by_role("tab")).to_have_count(8)
    expect(login.page.get_by_test_id("logout")).to_be_visible()


def test_session_cookie_is_http_only(login: LoginPage):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)
    cookie = session_cookie(login.page)
    assert cookie is not None
    assert cookie["httpOnly"] is True and cookie["sameSite"] == "Lax"
    # Page scripts can't read it.
    assert auth.COOKIE_NAME not in login.page.evaluate("document.cookie")


def test_username_is_not_case_sensitive(login: LoginPage):
    login.open()
    login.sign_in(f"  {TEST_USER.upper()} ", TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)


def test_enter_key_submits(login: LoginPage):
    login.open()
    login.username.fill(TEST_USER)
    login.password.fill(TEST_PASSWORD)
    login.password.press("Enter")
    expect(login.page).to_have_url(PORTFOLIO_URL)


# ---------- Wrong details ----------

def test_wrong_password_shows_error_and_keeps_username(login: LoginPage):
    login.open()
    login.sign_in(TEST_USER, "not-the-password")
    login.expect_error("Wrong username or password.")
    expect(login.page).to_have_url(LOGIN_URL)
    expect(login.username).to_have_value(TEST_USER)
    expect(login.password).to_have_value("")  # never echoed back
    expect(login.password).to_be_focused()
    assert session_cookie(login.page) is None


def test_wrong_username_shows_error(login: LoginPage):
    login.open()
    login.sign_in("someone-else", TEST_PASSWORD)
    login.expect_error("Wrong username or password.")
    assert session_cookie(login.page) is None


def test_password_is_case_sensitive(login: LoginPage):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD.upper())
    login.expect_error("Wrong username or password.")


def test_can_retry_after_a_wrong_password(login: LoginPage):
    login.open(next_path="/portfolio")
    login.sign_in(TEST_USER, "nope")
    login.expect_error("Wrong username or password.")
    login.password.fill(TEST_PASSWORD)
    login.submit.click()
    expect(login.page).to_have_url(PORTFOLIO_URL)


# ---------- Empty fields ----------

@pytest.mark.parametrize(
    "username, password, empty_field",
    [("", "", "username"), ("", TEST_PASSWORD, "username"), (TEST_USER, "", "password")],
    ids=["both-empty", "no-username", "no-password"],
)
def test_empty_fields_are_not_submitted(login: LoginPage, username, password, empty_field):
    login.open()
    login.username.fill(username)
    login.password.fill(password)
    login.submit.click()
    field = login.username if empty_field == "username" else login.password
    # The browser stops the form: still on the sign-in page, no server error, the empty field is flagged.
    expect(login.page).to_have_url(LOGIN_URL)
    expect(login.error).to_have_count(0)
    assert field.evaluate("el => el.validity.valueMissing") is True
    expect(field).to_be_focused()


def test_password_field_is_masked(login: LoginPage):
    login.open()
    expect(login.password).to_have_attribute("type", "password")
    expect(login.password).to_have_attribute("autocomplete", "current-password")
    expect(login.username).to_have_attribute("autocomplete", "username")
    expect(login.username).to_be_focused()


# ---------- Sign out ----------

def test_sign_out_locks_portfolio_again(login: LoginPage, live_server):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)

    login.page.get_by_test_id("logout").click()
    expect(login.page).to_have_url(f"{live_server}/")
    assert session_cookie(login.page) is None

    login.page.goto(f"{live_server}/portfolio")
    expect(login.page).to_have_url(LOGIN_URL)
    assert login.page.request.get(f"{live_server}/api/research/AAPL").status == 401


def test_back_button_after_sign_out_does_not_show_portfolio(login: LoginPage, live_server):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)
    login.page.get_by_test_id("logout").click()
    expect(login.page).to_have_url(f"{live_server}/")
    login.page.go_back()
    expect(login.page).to_have_url(LOGIN_URL)
    expect(login.page.get_by_test_id("portfolio")).to_have_count(0)


# ---------- Lockout ----------

def test_lockout_after_five_wrong_passwords(login: LoginPage):
    login.open()
    for _ in range(5):
        login.sign_in(TEST_USER, "wrong")
        login.expect_error("Wrong username or password.")
    login.sign_in(TEST_USER, TEST_PASSWORD)  # even the right password has to wait
    login.expect_error("Too many attempts. Wait 15 minutes and try again.")
    expect(login.page).to_have_url(LOGIN_URL)
    assert session_cookie(login.page) is None


# ---------- Staying signed in ----------

def test_stays_signed_in_across_reloads_tabs_and_pages(login: LoginPage, live_server):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)

    login.page.reload()
    expect(login.page).to_have_url(PORTFOLIO_URL)

    login.page.locator("[data-tab=health]").click()
    expect(login.page).to_have_url(re.compile(r"/news/health$"))
    login.page.locator("[data-tab=portfolio]").click()
    expect(login.page).to_have_url(PORTFOLIO_URL)

    other_tab = login.page.context.new_page()  # same browser, new tab
    other_tab.goto(f"{live_server}/portfolio")
    expect(other_tab).to_have_url(PORTFOLIO_URL)
    other_tab.close()


def test_sign_in_lasts_thirty_days(login: LoginPage):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)
    cookie = session_cookie(login.page)
    days_left = (cookie["expires"] - login.page.evaluate("Date.now() / 1000")) / 86400
    assert 29.9 < days_left <= 30


def test_sign_in_page_skips_ahead_when_already_signed_in(page: Page, live_server):
    # `page` starts signed in (see conftest).
    page.goto(f"{live_server}/login")
    expect(page).to_have_url(PORTFOLIO_URL)


def test_another_browser_is_not_signed_in(login: LoginPage, browser: Browser, live_server):
    login.open()
    login.sign_in(TEST_USER, TEST_PASSWORD)
    expect(login.page).to_have_url(PORTFOLIO_URL)
    other = browser.new_context()
    try:
        page = other.new_page()
        page.goto(f"{live_server}/portfolio")
        expect(page).to_have_url(LOGIN_URL)
    finally:
        other.close()


# ---------- Public pages and layouts ----------

def test_news_tabs_need_no_sign_in(anon_page: Page, live_server):
    for path in ("/", "/news/technology", "/news/health"):
        anon_page.goto(f"{live_server}{path}")
        expect(anon_page).to_have_url(f"{live_server}{path}")
        expect(anon_page.get_by_test_id("login")).to_have_count(0)


def test_sign_in_works_on_a_phone(browser: Browser, playwright, live_server):
    context = browser.new_context(**playwright.devices["iPhone 13"])
    try:
        login = LoginPage(context.new_page(), live_server).open()
        width = login.page.evaluate("document.documentElement.scrollWidth")
        assert width <= login.page.viewport_size["width"]  # no sideways scrolling
        login.sign_in(TEST_USER, TEST_PASSWORD)
        expect(login.page).to_have_url(PORTFOLIO_URL)
    finally:
        context.close()


def test_sign_in_page_in_dark_mode(browser: Browser, live_server):
    context = browser.new_context(color_scheme="dark")
    try:
        login = LoginPage(context.new_page(), live_server).open()
        expect(login.page.locator("html")).to_have_attribute("data-theme", "dark")
        login.sign_in(TEST_USER, "wrong")
        login.expect_error("Wrong username or password.")
    finally:
        context.close()
