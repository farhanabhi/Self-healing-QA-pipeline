"""
Mock data generation.

Centralises Faker usage so the mock server and the test suite generate
realistic, varied data from the same source instead of hard-coded fixtures
scattered across files.
"""
from __future__ import annotations

import uuid

from faker import Faker

fake = Faker()

_ITEMS = [
    "Wireless Mouse",
    "Mechanical Keyboard",
    "27-inch Monitor",
    "USB-C Docking Station",
    "Noise Cancelling Headphones",
    "Laptop Stand",
    "1TB NVMe SSD",
    "Webcam 1080p",
]


def generate_order() -> dict:
    """Returns a single realistic, randomised order record."""
    return {
        "order_id": f"ord_{uuid.uuid4().hex[:10]}",
        "customer_name": fake.name(),
        "item": fake.random_element(_ITEMS),
        "amount_cents": fake.random_int(min=999, max=49999),
        "status": "pending",
    }


def generate_user() -> dict:
    """Returns a realistic, randomised (non-privileged) user record."""
    return {
        "username": fake.user_name(),
        "email": fake.email(),
        "full_name": fake.name(),
    }


def generate_invalid_credentials(count: int = 3) -> list[tuple[str, str]]:
    """
    Randomised *wrong* username/password pairs for data-driven negative
    tests — deliberately never matches the seeded VALID_USER in main.py.
    """
    return [(fake.user_name(), fake.password(length=10)) for _ in range(count)]
