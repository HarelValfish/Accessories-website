"""
order_generator.py
──────────────────
Utility for generating unique human-readable order numbers.
Format: ORD-YYYYMMDD-XXXX (e.g., ORD-20260426-A3F9)
"""

import secrets
from datetime import datetime, timezone


def generate_order_number() -> str:
    """
    Generate a unique order number in format: ORD-YYYYMMDD-XXXX
    Example: ORD-20260426-A3F9

    The random suffix makes it extremely unlikely to have collisions,
    and the database index ensures uniqueness.
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")  # e.g., 20260426
    random_part = secrets.token_hex(2).upper()        # e.g., A3F9 (4 hex chars)

    return f"ORD-{date_part}-{random_part}"
