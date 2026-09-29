"""
LoginPage
=========
Page object for the mock login UI. Locators are declared once, at the top,
per POM convention. Note that ``LOGIN_BUTTON`` intentionally targets the
*stable* selector (``#login-btn``) — when this page object is driven
against ``/login?variant=drifted``, that selector no longer exists on the
page, which is precisely the scenario the self-healing test exercises.
"""
from __future__ import annotations

from pages.base_page import BasePage


class LoginPage(BasePage):
    # --- Locators -------------------------------------------------------
    USERNAME_INPUT = "#username"
    PASSWORD_INPUT = "#password"
    LOGIN_BUTTON = "#login-btn"
    RESULT_BANNER = "#result"

    # --- Navigation -------------------------------------------------------
    def open(self, variant: str = "stable") -> None:
        self.goto(f"/login?variant={variant}")

    # --- Actions -------------------------------------------------------
    def login(self, username: str, password: str) -> None:
        self.safe_fill(self.USERNAME_INPUT, username, description="username input field")
        self.safe_fill(self.PASSWORD_INPUT, password, description="password input field")
        self.safe_click(self.LOGIN_BUTTON, description="primary login submit button")

    # --- Assertions / state -------------------------------------------------------
    def is_login_successful(self, expected_username: str) -> bool:
        if not self.safe_is_visible("#welcome-message", "post-login welcome banner", timeout_ms=5000):
            return False
        text = self.safe_get_text("#welcome-message", "post-login welcome banner")
        return expected_username in text

    def get_result_text(self) -> str:
        return self.safe_get_text(self.RESULT_BANNER, "login result / error banner")
