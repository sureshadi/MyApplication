import pytest
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e

PAGES = ["/", "/news/technology", "/news/health", "/portfolio", "/ticker/AAPL"]


def theme(page: Page) -> str | None:
    return page.evaluate("document.documentElement.getAttribute('data-theme')")


def bg(page: Page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_default_follows_system_color_scheme(browser: Browser, live_server, scheme):
    context = browser.new_context(color_scheme=scheme)
    page = context.new_page()
    try:
        page.goto(live_server)
        assert theme(page) == scheme
        expect(page.get_by_test_id("theme-toggle")).to_have_attribute("aria-pressed", "true" if scheme == "dark" else "false")
    finally:
        context.close()


def test_toggle_switches_and_persists_across_reloads_and_pages(browser: Browser, live_server):
    context = browser.new_context(color_scheme="light")
    page = context.new_page()
    try:
        page.goto(live_server)
        toggle = page.get_by_role("button", name="Dark mode")
        assert theme(page) == "light"
        light_bg = bg(page)

        toggle.click()
        assert theme(page) == "dark"
        expect(toggle).to_have_attribute("aria-pressed", "true")
        assert bg(page) != light_bg
        assert page.evaluate("localStorage.getItem('theme')") == "dark"

        page.reload()
        assert theme(page) == "dark"
        expect(page.get_by_test_id("theme-toggle")).to_have_attribute("aria-pressed", "true")

        # The explicit choice beats the system setting on every page.
        for path in PAGES:
            page.goto(live_server + path)
            assert theme(page) == "dark", path

        page.get_by_test_id("theme-toggle").click()
        assert theme(page) == "light"
        page.reload()
        assert theme(page) == "light"
        assert page.evaluate("localStorage.getItem('theme')") == "light"
    finally:
        context.close()


def test_saved_choice_overrides_dark_system_setting(browser: Browser, live_server):
    context = browser.new_context(color_scheme="dark")
    context.add_init_script("try { localStorage.setItem('theme', 'light') } catch (e) {}")
    page = context.new_page()
    try:
        page.goto(live_server)
        assert theme(page) == "light"
    finally:
        context.close()


def test_toggle_is_keyboard_usable(page: Page, live_server):
    page.emulate_media(color_scheme="light")
    page.goto(live_server)
    toggle = page.get_by_test_id("theme-toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    assert theme(page) == "dark"
    page.keyboard.press("Space")
    assert theme(page) == "light"


def test_follows_system_change_until_user_chooses(page: Page, live_server):
    page.emulate_media(color_scheme="light")
    page.goto(live_server)
    assert theme(page) == "light"
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("document.documentElement.getAttribute('data-theme') === 'dark'")


@pytest.mark.parametrize("path", PAGES)
def test_toggle_visible_on_every_page(page: Page, live_server, path):
    page.goto(live_server + path)
    expect(page.get_by_test_id("theme-toggle")).to_be_visible()


def test_toggle_visible_on_phone_without_horizontal_scroll(page: Page, live_server):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_server)
    expect(page.get_by_test_id("theme-toggle")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
