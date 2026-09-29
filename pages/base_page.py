"""
BasePage
========
Every concrete page object inherits from this. It owns the raw Playwright
`Page` handle and exposes a small vocabulary of self-healing-wrapped
actions (`safe_click`, `safe_fill`, `safe_get_text`, `safe_is_visible`) so
that no page object ever calls `page.locator(...).click()` directly —
UI element interaction, self-healing, and test assertions stay fully
decoupled, as required by an enterprise POM structure.
"""
from __future__ import annotations

from playwright.sync_api import Page

from utils.config import settings
from utils.healer import SelfHealer


class BasePage:
    def __init__(self, page: Page, healer: SelfHealer | None = None) -> None:
        self.page = page
        self.healer = healer or SelfHealer()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def goto(self, path: str) -> None:
        base = settings.mock_server_url.rstrip("/")
        self.page.goto(f"{base}{path}")

    # ------------------------------------------------------------------
    # Self-healing-wrapped interactions
    # ------------------------------------------------------------------
    def safe_click(self, selector: str, description: str) -> None:
        def _click(locator):
            locator.click(timeout=settings.default_action_timeout_ms)

        self.healer.run_with_healing(self.page, selector, description, _click)

    def safe_fill(self, selector: str, value: str, description: str) -> None:
        def _fill(locator):
            locator.fill(value, timeout=settings.default_action_timeout_ms)

        self.healer.run_with_healing(self.page, selector, description, _fill)

    def safe_get_text(self, selector: str, description: str) -> str:
        holder: dict[str, str] = {}

        def _get_text(locator):
            holder["value"] = locator.inner_text(timeout=settings.default_action_timeout_ms)

        self.healer.run_with_healing(self.page, selector, description, _get_text)
        return holder.get("value", "")

    def safe_is_visible(self, selector: str, description: str, timeout_ms: int | None = None) -> bool:
        """
        Pure existence/visibility check. Deliberately NOT routed through the
        healer — asserting something is absent should never trigger a
        selector-repair attempt.
        """
        try:
            self.page.locator(selector).wait_for(
                state="visible", timeout=timeout_ms or settings.default_action_timeout_ms
            )
            return True
        except Exception:
            return False
