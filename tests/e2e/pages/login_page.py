"""Page object for the Portfolio sign-in page, so tests read as user steps."""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect


class LoginPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url
        self.heading = page.get_by_role("heading", name="Sign in to Portfolio")
        self.username: Locator = page.get_by_label("Username")
        self.password: Locator = page.get_by_label("Password")
        self.submit: Locator = page.get_by_role("button", name="Sign in")
        self.error: Locator = page.get_by_test_id("login-error")

    def open(self, next_path: str | None = None) -> "LoginPage":
        self.page.goto(f"{self.base_url}/login" + (f"?next={next_path}" if next_path else ""))
        expect(self.heading).to_be_visible()
        return self

    def sign_in(self, username: str, password: str) -> None:
        self.username.fill(username)
        self.password.fill(password)
        self.submit.click()

    def expect_error(self, text: str) -> None:
        expect(self.error).to_be_visible()
        expect(self.error).to_have_text(text)
