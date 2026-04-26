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
from functools import wraps
from flask import session, redirect, url_for

# ── Admin password — read from environment variable ────────────────────────────
# Set ADMIN_PASSWORD in your .env file to change it.
# Default is "admin1234" for local development only — change before going live.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")


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
    @wraps(f)  # preserve the original function's name and docstring
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):  # check session flag
            return redirect(url_for("auth.admin_login"))  # send to login page
        return f(*args, **kwargs)  # user is authenticated — proceed
    return decorated_function


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: check_password
# ══════════════════════════════════════════════════════════════════════════════

def check_password(entered: str) -> bool:
    """
    Compare the password entered in the login form against the stored admin password.
    Returns True if they match, False otherwise.

    Note: For production, consider using werkzeug.security.check_password_hash
    instead of plain string comparison.
    """
    return entered == ADMIN_PASSWORD  # simple equality check
