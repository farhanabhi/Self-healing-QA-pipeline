"""
End-to-end workflow suite.

Combines API validation, UI state verification, AI self-healing verification,
and negative/security test cases against the mock service virtualization
layer. Every test resets mock-server state first (see `reset_mock_state`
autouse fixture in conftest.py), so tests are independent and can run in
any order or in parallel under pytest-xdist.
"""
from __future__ import annotations

import uuid

import allure
import httpx
import pytest

from pages.login_page import LoginPage
from utils.config import settings
from utils.mock_data import generate_invalid_credentials

VALID_USERNAME = "qa_engineer"
VALID_PASSWORD = "S3lfHeal!ng"


# ---------------------------------------------------------------------------
# 1. Pure API validation
# ---------------------------------------------------------------------------
@allure.feature("Mock Service Virtualization")
@allure.story("Health & Orders API")
@pytest.mark.smoke
class TestApiContracts:
    def test_health_check(self, api_client: httpx.Client) -> None:
        response = api_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_orders_are_seeded_on_reset(self, api_client: httpx.Client) -> None:
        response = api_client.get("/api/orders")
        assert response.status_code == 200
        orders = response.json()
        assert len(orders) == 3
        assert all(order["status"] == "pending" for order in orders)

    def test_create_order_returns_valid_schema(self, api_client: httpx.Client) -> None:
        response = api_client.post("/api/orders")
        assert response.status_code == 201
        body = response.json()
        for field in ("order_id", "customer_name", "item", "amount_cents", "status"):
            assert field in body


# ---------------------------------------------------------------------------
# 2. Resilience: deterministic flaky-gateway retry behaviour
# ---------------------------------------------------------------------------
@allure.feature("Mock Service Virtualization")
@allure.story("Flaky Payment Gateway Resilience")
@pytest.mark.e2e
class TestPaymentResilience:
    def test_first_attempt_fails_and_retry_succeeds(self, api_client: httpx.Client) -> None:
        orders = api_client.get("/api/orders").json()
        order_id = orders[0]["order_id"]
        idempotency_key = str(uuid.uuid4())
        payload = {"order_id": order_id, "amount_cents": 4999, "idempotency_key": idempotency_key}

        with allure.step("First call hits the cold upstream and fails with 503"):
            first = api_client.post("/api/payment", json=payload)
            assert first.status_code == 503

        with allure.step("Retry with the same idempotency key succeeds"):
            second = api_client.post("/api/payment", json=payload)
            assert second.status_code == 200
            body = second.json()
            assert body["status"] == "success"
            assert body["attempt"] == 2

    def test_unknown_order_is_rejected(self, api_client: httpx.Client) -> None:
        payload = {"order_id": "ord_does_not_exist", "amount_cents": 100, "idempotency_key": str(uuid.uuid4())}
        response = api_client.post("/api/payment", json=payload)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3. Full E2E: API seed + UI login + state verification
# ---------------------------------------------------------------------------
@allure.feature("End-to-End User Journey")
@allure.story("Happy Path Login")
@pytest.mark.e2e
def test_e2e_login_happy_path(login_page: LoginPage) -> None:
    with allure.step("Open the stable login page"):
        login_page.open(variant="stable")

    with allure.step("Submit valid credentials"):
        login_page.login(VALID_USERNAME, VALID_PASSWORD)

    with allure.step("Assert the welcome banner reflects the logged-in user"):
        assert login_page.is_login_successful(expected_username=VALID_USERNAME)


# ---------------------------------------------------------------------------
# 4. AI self-healing verification
# ---------------------------------------------------------------------------
@allure.feature("AI Self-Healing")
@allure.story("Selector Drift Recovery")
@pytest.mark.self_healing
@pytest.mark.skipif(
    not settings.self_healing_available,
    reason="GROQ_API_KEY not configured — self-healing demo requires a live LLM key.",
)
def test_self_healing_recovers_from_selector_drift(login_page: LoginPage) -> None:
    """
    The mock UI's 'drifted' variant renames the login button id, but
    LoginPage still targets the OLD id (#login-btn). safe_click() must
    detect the timeout, ask the LLM for a corrected selector against the
    live DOM, validate it, and complete the click transparently.
    """
    with allure.step("Open the DRIFTED login page (button id has silently changed)"):
        login_page.open(variant="drifted")

    with allure.step("Attempt login using the now-stale selector — self-healing should kick in"):
        login_page.login(VALID_USERNAME, VALID_PASSWORD)

    with allure.step("Login still succeeds despite the DOM change"):
        assert login_page.is_login_successful(expected_username=VALID_USERNAME)


# ---------------------------------------------------------------------------
# 5. Negative / security test cases
# ---------------------------------------------------------------------------
@allure.feature("Security")
@allure.story("Authentication Hardening")
@pytest.mark.security
class TestAuthSecurity:
    @pytest.mark.parametrize(
        "malicious_username",
        [
            "' OR '1'='1",
            "admin'--",
            "<script>alert(1)</script>",
            "'; DROP TABLE users;--",
        ],
    )
    def test_injection_style_payloads_are_rejected_as_bad_credentials(
        self, api_client: httpx.Client, malicious_username: str
    ) -> None:
        response = api_client.post(
            "/api/security/login",
            json={"username": malicious_username, "password": "irrelevant"},
        )
        assert response.status_code == 200  # request is well-formed...
        body = response.json()
        assert body["success"] is False  # ...but never authenticates
        assert body.get("token") is None

    @pytest.mark.parametrize("username,password", generate_invalid_credentials(count=3))
    def test_random_invalid_credentials_are_rejected(
        self, api_client: httpx.Client, username: str, password: str
    ) -> None:
        response = api_client.post(
            "/api/security/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        assert response.json()["success"] is False

    def test_login_ui_surfaces_error_on_bad_credentials(self, login_page: LoginPage) -> None:
        login_page.open(variant="stable")
        login_page.login("not_a_real_user", "wrong_password")
        assert not login_page.is_login_successful(expected_username="not_a_real_user")
        assert "invalid" in login_page.get_result_text().lower()
