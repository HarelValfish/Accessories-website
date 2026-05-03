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
from flask import Flask, request
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flasgger import Swagger

# Initialize extensions (will be bound to app in create_app)
# These must be defined before routes.py is imported so that routes.py
# can import limiter at module level for use as a decorator.
bcrypt = Bcrypt()
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)

from routes import public_bp, admin_bp, auth_bp, api_bp, user_bp  # import all blueprints
from errors import register_error_handlers                        # global error pages


def create_app() -> Flask:
    """
    Application factory function.

    Returns a fully configured Flask app.
    Calling it as a function (rather than just setting up app at module level)
    makes it easy to create test instances or multiple configurations.
    """
    app = Flask(__name__)  # create the Flask application

    # ── Secret key for signing session cookies ─────────────────────────────────
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY environment variable must be set before starting the app")
    app.secret_key = secret_key

    # ── Email configuration ────────────────────────────────────────────────────
    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "localhost")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 25))
    app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "False") == "True"
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")

    # ── Initialize extensions ──────────────────────────────────────────────────
    bcrypt.init_app(app)   # password hashing
    csrf.init_app(app)     # CSRF protection for forms
    mail.init_app(app)     # must come after MAIL_* config is set
    limiter.init_app(app)  # rate limiting

    # ── Security headers ───────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── Register Blueprints ────────────────────────────────────────────────────
    # Each blueprint groups a set of related routes together.
    # url_prefix is intentionally left off here because each blueprint already
    # has its full path defined inside routes.py (e.g. "/admin", "/api/...").
    app.register_blueprint(public_bp)  # storefront: /, /item/<id>
    app.register_blueprint(auth_bp)    # auth: /admin/login, /admin/logout
    app.register_blueprint(admin_bp)   # admin panel: /admin, /admin/item/...
    app.register_blueprint(api_bp)     # JSON API: /api/fetch-image
    app.register_blueprint(user_bp)    # user: /register, /login, /cart, /checkout, /account

    # ── API documentation (Swagger UI at /api/docs) ────────────────────────────
    Swagger(app, config={
        "headers": [],
        "specs": [{
            "endpoint": "apispec",
            "route": "/api/spec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/api/docs",
    }, template={
        "swagger": "2.0",
        "info": {
            "title": "TechDen API",
            "description": (
                "REST and HTML API for the TechDen computer accessories store.\n\n"
                "**Authentication:**\n"
                "- Admin routes require an active admin session (POST `/admin/login`).\n"
                "- User routes that require login redirect to `/login` if unauthenticated.\n"
                "- JSON endpoints expecting a session will return `302` without one.\n\n"
                "**Rate limits:** `/admin/login` 5/min · `/login` 10/min (per IP)."
            ),
            "version": "1.0",
        },
        "basePath": "/",
        "schemes": ["http", "https"],
        "tags": [
            {"name": "Storefront",          "description": "Public product pages"},
            {"name": "Admin Auth",          "description": "Admin login / logout"},
            {"name": "Admin – Items",       "description": "Product CRUD (admin)"},
            {"name": "Admin – Sales",       "description": "Sale management (admin)"},
            {"name": "Admin – Analytics",   "description": "Analytics dashboard (admin)"},
            {"name": "Admin – Users",       "description": "User management (admin)"},
            {"name": "Admin – Orders",      "description": "Order management (admin)"},
            {"name": "Images API",          "description": "Image auto-fetch JSON endpoints"},
            {"name": "Categories API",      "description": "Category JSON endpoints"},
            {"name": "User Auth",           "description": "User registration and login"},
            {"name": "Cart",                "description": "Shopping cart"},
            {"name": "Checkout",            "description": "Order placement"},
            {"name": "Account",             "description": "User account and order history"},
        ],
    })

    # ── Register error handlers ────────────────────────────────────────────────
    register_error_handlers(app)       # 404 and 500 pages from errors.py

    return app
