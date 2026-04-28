"""
user_auth.py
────────────
User authentication decorators and helpers.
Separate from admin authentication to maintain clear separation of concerns.
"""

import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import session, redirect, url_for, request
from bson import ObjectId

from database import users_collection


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user():
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
            user["_id"] = str(user["_id"])  # convert ObjectId to string
        return user
    except Exception:
        return None


def user_login_required(f):
    """
    Decorator to protect routes that require user authentication.
    Redirects to login page if user is not logged in.

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
        return f(*args, **kwargs)
    return decorated_function


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL VERIFICATION TOKENS
# ══════════════════════════════════════════════════════════════════════════════

def generate_verification_token():
    """
    Generate a secure random token for email verification.
    Returns a tuple of (token, expiration_datetime).
    """
    token = secrets.token_urlsafe(32)  # 43-char URL-safe string
    expires_at = datetime.utcnow() + timedelta(hours=24)  # 24-hour expiration
    return token, expires_at


def verify_token(token: str) -> dict | None:
    """
    Verify an email verification token and return the user if valid.
    Returns None if token is invalid or expired.
    """
    if not token:
        return None

    # Find user with this token
    user = users_collection.find_one({"verification_token": token})
    if not user:
        return None

    # Check if token has expired
    if user.get("token_expires_at") and user["token_expires_at"] < datetime.utcnow():
        return None

    return user
