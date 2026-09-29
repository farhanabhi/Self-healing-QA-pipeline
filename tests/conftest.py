from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

import allure
import httpx
import pytest
from playwright.sync_api import Page

from pages.login_page import LoginPage
from utils.config import settings
from utils.healer import SelfHealer

logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Playwright browser configuration (pytest-playwright reads these fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    return {**browser_type_launch_args, "headless": settings.headless, "slow_mo": settings.slow_mo_ms}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    return {**browser_context_args, "viewport": {"width": 1280, "height": 800}}


# ---------------------------------------------------------------------------
# API client + deterministic state
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_client() -> Generator[httpx.Client, None, None]:
    with httpx.Client(base_url=settings.mock_server_url, timeout=10.0) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_mock_state(api_client: httpx.Client) -> None:
    """Every test starts from clean, deterministic mock-server state."""
    response = api_client.post("/api/reset")
    response.raise_for_status()


# ---------------------------------------------------------------------------
# Page objects
# ---------------------------------------------------------------------------
@pytest.fixture
def healer() -> SelfHealer:
    return SelfHealer()


@pytest.fixture
def login_page(page: Page, healer: SelfHealer) -> LoginPage:
    return LoginPage(page, healer)


# ---------------------------------------------------------------------------
# Allure environment metadata + failure diagnostics
# ---------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    results_dir = Path(settings.allure_results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    env_file = results_dir / "environment.properties"
    env_file.write_text(
        "\n".join(
            [
                f"environment={settings.environment}",
                f"mock_server_url={settings.mock_server_url}",
                f"self_healing_enabled={settings.self_healing_enabled}",
                f"self_healing_available={settings.self_healing_available}",
                f"groq_model={settings.groq_model}",
                f"headless={settings.headless}",
            ]
        )
    )


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """Attaches a screenshot to Allure automatically whenever a UI test fails."""
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    page: Page | None = item.funcargs.get("page")
    if page is None:
        return

    try:
        allure.attach(
            page.screenshot(full_page=True),
            name="Failure Screenshot",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            page.content(),
            name="Failure DOM Snapshot",
            attachment_type=allure.attachment_type.HTML,
        )
    except Exception:
        pass  # never let reporting instrumentation mask the real failure
