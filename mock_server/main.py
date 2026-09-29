"""
Mock Service Virtualization Layer
==================================
A self-contained FastAPI application that stands in for three things the
real system under test would otherwise depend on:

1. A tiny login UI (served as plain HTML) that the Playwright suite drives.
   It ships in two "variants" so the AI self-healing mechanism has something
   real to prove itself against:
     * ``/login``            -> stable DOM, button id="login-btn"
     * ``/login?variant=drifted`` -> simulates a front-end release that
       renamed the button to id="submit-action-primary" with no other
       change. Page objects that hard-code the old selector will fail here
       until the healer patches itself.

2. A "flaky" upstream payment gateway (``/api/payment``) that deterministically
   fails on a resource's first call and succeeds on retry, so resilience /
   retry logic can be tested without relying on real network flakiness.

3. A hardened auth endpoint (``/api/security/login``) used for negative /
   security test cases (e.g. injection-style payloads must be rejected as
   plain bad credentials, never treated as executable input).

Everything is in-memory; state resets via ``POST /api/reset`` so the suite
stays deterministic and idempotent across runs.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from utils.mock_data import generate_order, generate_user

APP_START = time.time()
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Mock Service Virtualization Layer",
    description="Deterministic stand-in for a flaky upstream microservice + login UI.",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
VALID_USER = {"username": "qa_engineer", "password": "S3lfHeal!ng"}
ORDERS: dict[str, dict] = {}
# Tracks how many times each idempotency key has hit /api/payment, so the
# first call for a given key can deterministically fail and the retry succeed.
PAYMENT_ATTEMPTS: dict[str, int] = {}


def _reset_state() -> None:
    ORDERS.clear()
    PAYMENT_ATTEMPTS.clear()
    for _ in range(3):
        order = generate_order()
        ORDERS[order["order_id"]] = order


_reset_state()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., max_length=128)
    password: str = Field(..., max_length=128)


class LoginResponse(BaseModel):
    success: bool
    message: str
    token: str | None = None


class PaymentRequest(BaseModel):
    order_id: str
    amount_cents: int = Field(..., gt=0)
    idempotency_key: str


class PaymentResponse(BaseModel):
    status: Literal["success"]
    order_id: str
    transaction_id: str
    attempt: int


class OrderResponse(BaseModel):
    order_id: str
    customer_name: str
    item: str
    amount_cents: int
    status: str


# ---------------------------------------------------------------------------
# Health & lifecycle
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "uptime_seconds": round(time.time() - APP_START, 2)}


@app.post("/api/reset", tags=["ops"])
def reset() -> dict:
    """Restores deterministic starting state between test runs."""
    _reset_state()
    return {"status": "reset", "orders_seeded": len(ORDERS)}


# ---------------------------------------------------------------------------
# UI under test: login page (stable + drifted DOM variants)
# ---------------------------------------------------------------------------
_LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>QA Platform :: Login</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <div class="card">
    <h1>Sign in to continue</h1>
    <form id="login-form" autocomplete="off">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" />

      <label for="password">Password</label>
      <input id="password" name="password" type="password" />

      <button id="{button_id}" type="submit">Log in</button>
    </form>
    <div id="result"></div>
  </div>

  <script>
    document.getElementById("login-form").addEventListener("submit", async (e) => {{
      e.preventDefault();
      const username = document.getElementById("username").value;
      const password = document.getElementById("password").value;
      const resultEl = document.getElementById("result");
      resultEl.textContent = "Checking...";
      resultEl.className = "";
      try {{
        const res = await fetch("/api/security/login", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ username, password }})
        }});
        const data = await res.json();
        if (res.ok && data.success) {{
          resultEl.textContent = "Welcome, " + username + "!";
          resultEl.id = "welcome-message";
          resultEl.className = "success";
        }} else {{
          resultEl.textContent = data.message || "Login failed";
          resultEl.className = "error";
        }}
      }} catch (err) {{
        resultEl.textContent = "Network error";
        resultEl.className = "error";
      }}
    }});
  </script>
</body>
</html>
"""


@app.get("/login", response_class=HTMLResponse, tags=["ui"])
def login_page(variant: Literal["stable", "drifted"] = "stable") -> str:
    """
    Serves the login UI. ``variant=drifted`` renames the submit button's id
    to emulate an unannounced front-end change, which is exactly the class
    of breakage the self-healing layer exists to survive.
    """
    button_id = "login-btn" if variant == "stable" else "submit-action-primary"
    return _LOGIN_TEMPLATE.format(button_id=button_id)


# ---------------------------------------------------------------------------
# Hardened auth endpoint (target for negative / security tests)
# ---------------------------------------------------------------------------
@app.post("/api/security/login", response_model=LoginResponse, tags=["auth"])
def secure_login(payload: LoginRequest) -> LoginResponse:
    """
    Intentionally simple credential check using strict equality — there is
    no string concatenation into a query and no template evaluation of
    user input, so classic injection-style payloads (e.g. ``' OR '1'='1``)
    are just wrong passwords here, never executable input. This lets the
    suite assert that malicious-looking input degrades safely rather than
    being interpreted.
    """
    is_valid = (
        payload.username == VALID_USER["username"]
        and payload.password == VALID_USER["password"]
    )
    if not is_valid:
        return LoginResponse(success=False, message="Invalid username or password")
    return LoginResponse(success=True, message="Authenticated", token=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Flaky upstream payment gateway
# ---------------------------------------------------------------------------
@app.post("/api/payment", response_model=PaymentResponse, tags=["payments"])
def process_payment(payload: PaymentRequest) -> PaymentResponse:
    if payload.order_id not in ORDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown order_id")

    attempt = PAYMENT_ATTEMPTS.get(payload.idempotency_key, 0) + 1
    PAYMENT_ATTEMPTS[payload.idempotency_key] = attempt

    if attempt == 1:
        # Deterministic "flakiness": the FIRST call for any idempotency key
        # always fails, simulating a cold upstream / gateway timeout.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upstream payment gateway timed out. Retry with the same idempotency key.",
        )

    ORDERS[payload.order_id]["status"] = "paid"
    return PaymentResponse(
        status="success",
        order_id=payload.order_id,
        transaction_id=f"txn_{uuid.uuid4().hex[:12]}",
        attempt=attempt,
    )


# ---------------------------------------------------------------------------
# Orders API (backing data for UI + data-driven tests)
# ---------------------------------------------------------------------------
@app.get("/api/orders", response_model=list[OrderResponse], tags=["orders"])
def list_orders() -> list[dict]:
    return list(ORDERS.values())


@app.get("/api/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def get_order(order_id: str) -> dict:
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@app.post("/api/orders", response_model=OrderResponse, status_code=201, tags=["orders"])
def create_order() -> dict:
    """Creates a fresh, Faker-generated order — used to seed data-driven tests."""
    order = generate_order()
    ORDERS[order["order_id"]] = order
    return order


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
