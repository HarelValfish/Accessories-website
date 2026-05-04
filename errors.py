"""
errors.py
─────────
Registers global HTTP error handlers on the Flask app.

Handles:
  - 404 Not Found
  - 500 Internal Server Error

Imported and called by app.py via register_error_handlers(app).
"""

from flask import Flask, render_template


def register_error_handlers(app: Flask) -> None:
    """Attach error-handling views to the Flask app instance."""

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("500.html"), 500
