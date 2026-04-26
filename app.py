"""
app.py
──────
Flask application factory.

Responsibilities:
  - Create and configure the Flask app object
  - Register all Blueprints (route groups) from routes.py
  - Set the secret key used for session encryption

This file does NOT define any routes itself — those all live in routes.py.
"""

import os
from flask import Flask

from routes import public_bp, admin_bp, auth_bp, api_bp  # import all blueprints
from errors import register_error_handlers                # global error pages


def create_app() -> Flask:
    """
    Application factory function.

    Returns a fully configured Flask app.
    Calling it as a function (rather than just setting up app at module level)
    makes it easy to create test instances or multiple configurations.
    """
    app = Flask(__name__)  # create the Flask application

    # ── Secret key for signing session cookies ─────────────────────────────────
    # Flask uses this to encrypt the session data stored in the browser cookie.
    # IMPORTANT: Set SECRET_KEY in your .env file before deploying.
    app.secret_key = os.environ.get("SECRET_KEY", "techden-dev-secret-key")

    # ── Register Blueprints ────────────────────────────────────────────────────
    # Each blueprint groups a set of related routes together.
    # url_prefix is intentionally left off here because each blueprint already
    # has its full path defined inside routes.py (e.g. "/admin", "/api/...").
    app.register_blueprint(public_bp)  # storefront: /, /item/<id>
    app.register_blueprint(auth_bp)    # auth: /admin/login, /admin/logout
    app.register_blueprint(admin_bp)   # admin panel: /admin, /admin/item/...
    app.register_blueprint(api_bp)     # JSON API: /api/fetch-image

    # ── Register error handlers ────────────────────────────────────────────────
    register_error_handlers(app)       # 404 and 500 pages from errors.py

    return app
