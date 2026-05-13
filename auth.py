"""
auth.py
───────
Handles all authentication logic for the admin panel:
  - Reading the admin password from environment variables
  - The `login_required` decorator that protects admin routes
  - The `check_password` helper used by the login route

No database access here — auth is purely session-based.
"""

import os
import hmac
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import session, redirect, url_for

# ── Admin password — read from environment variable ────────────────────────────
# Set ADMIN_PASSWORD in your .env file. No default — startup fails if unset.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD environment variable must be set")


# ══════════════════════════════════════════════════════════════════════════════
#  DECORATOR: login_required
# ══════════════════════════════════════════════════════════════════════════════

def login_required(f):
    """
    Route decorator that blocks unauthenticated users from accessing admin pages.

    Usage:
        @app.route("/admin/something")
        @login_required          ← add this line below @app.route
        def some_admin_view():
            ...

    How it works:
        1. Before running the view function, it checks if "admin_logged_in" is
           stored in the Flask session (set to True after a successful login).
        2. If not logged in → redirect to the login page.
        3. If logged in → run the original view function normally.
    """
    TIMEOUT = timedelta(minutes=5)

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("auth.admin_login"))

        # Check 5-minute inactivity timeout
        last_seen_str = session.get("admin_last_seen")
        if last_seen_str:
            last_seen = datetime.fromisoformat(last_seen_str)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_seen > TIMEOUT:
                session.pop("admin_logged_in", None)
                session.pop("admin_last_seen", None)
                return redirect(url_for("auth.admin_login", expired=1))
        else:
            # No timestamp recorded — treat as expired
            session.pop("admin_logged_in", None)
            return redirect(url_for("auth.admin_login", expired=1))

        # Reset the timer on every admin page visit
        session["admin_last_seen"] = datetime.now(timezone.utc).isoformat()
        return f(*args, **kwargs)
    return decorated_function


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: check_password
# ══════════════════════════════════════════════════════════════════════════════

def check_password(entered: str) -> bool:
    """
    Compare the submitted admin password against the value from ADMIN_PASSWORD env var.
    Uses hmac.compare_digest to prevent timing-based enumeration attacks.
    The password itself is stored as plain text in the env var (not hashed) by design
    — the admin panel is a single-user tool behind a 5-minute inactivity timeout.
    """
    return hmac.compare_digest(entered, ADMIN_PASSWORD)
