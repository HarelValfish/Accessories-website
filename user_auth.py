"""
user_auth.py
────────────
User authentication decorators and helpers.
Separate from admin authentication to maintain clear separation of concerns.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import session, redirect, url_for, request
from bson import ObjectId

from database import users_collection

USER_TIMEOUT = timedelta(minutes=30)


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user() -> dict | None:
    """
    Get the currently logged-in user from the session.
    Returns the user document or None if not logged in.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except Exception:
        return None


def user_login_required(f):
    """
    Decorator to protect routes that require user authentication.
    Redirects to login page if user is not logged in or session has timed out.

    Usage:
        @app.route("/account")
        @user_login_required
        def account():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("user.login", next=request.path))

        # 30-minute inactivity timeout
        last_seen_str = session.get("user_last_seen")
        if not last_seen_str:
            session.pop("user_id", None)
            return redirect(url_for("user.login", next=request.path, expired=1))
        last_seen = datetime.fromisoformat(last_seen_str)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_seen > USER_TIMEOUT:
            session.pop("user_id", None)
            session.pop("user_last_seen", None)
            return redirect(url_for("user.login", next=request.path, expired=1))
        # Reset timer on every protected page visit
        session["user_last_seen"] = datetime.now(timezone.utc).isoformat()
        return f(*args, **kwargs)
    return decorated_function


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL VERIFICATION TOKENS
# ══════════════════════════════════════════════════════════════════════════════

def generate_verification_token() -> tuple[str, datetime]:
    """
    Generate a secure random token for email verification.
    Returns a tuple of (token, expiration_datetime).
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=24)
    return token, expires_at


def verify_token(token: str) -> dict | None:
    """
    Verify an email verification token and return the user if valid.
    Returns None if token is invalid or expired.
    """
    if not token:
        return None

    user = users_collection.find_one({"verification_token": token})
    if not user:
        return None

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    if user.get("token_expires_at") and user["token_expires_at"] < now_naive:
        return None

    return user
