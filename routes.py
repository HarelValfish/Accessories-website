"""
routes.py
─────────
Defines all URL routes for the app using Flask Blueprints.

Three blueprints:
  - public_bp  → storefront pages (/, /item/<id>)
  - admin_bp   → admin panel pages (/admin, /admin/item/...)
  - auth_bp    → login / logout (/admin/login, /admin/logout)
  - api_bp     → JSON endpoints (/api/fetch-image)

Blueprints are registered onto the Flask app in app.py.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, jsonify
)
import json

logger = logging.getLogger(__name__)

_JERUSALEM = ZoneInfo("Asia/Jerusalem")
_UTC = timezone.utc

from app    import bcrypt
from auth   import login_required, check_password
from models import (
    get_all_items, get_item_by_id, get_all_categories,
    get_all_categories_with_ids, get_or_create_category,
    create_item, update_item, delete_item, fetch_image, fetch_images, decrement_stock,
    set_item_sale, clear_item_sale, get_sale_info
)
from user_auth import user_login_required, get_current_user
from user_models import (
    create_user, get_user_by_email, get_user_by_id, verify_user_email,
    get_user_orders, get_order_by_id, create_order,
    get_all_users_with_stats, get_all_orders,
    update_user, delete_user
)
from cart_helpers import (
    add_to_cart as cart_add, remove_from_cart,
    update_cart_quantity, get_cart, get_cart_total, clear_cart,
    validate_cart_stock
)
from email_service import send_verification_email, send_order_confirmation
from order_generator import generate_order_number
from analytics import record_item_view, dashboard_payload


# ══════════════════════════════════════════════════════════════════════════════
#  SALE DATETIME HELPERS  (module-level so tests can import them directly)
# ══════════════════════════════════════════════════════════════════════════════

def _sale_dt_from_form(value: Optional[str]) -> Optional[datetime]:
    """
    Parse a datetime-local form field (Jerusalem local time) to a naive UTC datetime.
    Returns None for empty or invalid input.
    """
    if not value:
        return None
    try:
        local_dt = datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M").replace(tzinfo=_JERUSALEM)
        return local_dt.astimezone(_UTC).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _sale_dt_to_form(dt: Optional[datetime]) -> str:
    """
    Convert a naive UTC datetime to a Jerusalem datetime-local string for form display.
    Returns "" if dt is None.
    """
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_JERUSALEM).strftime("%Y-%m-%dT%H:%M")


# ══════════════════════════════════════════════════════════════════════════════
#  BLUEPRINT DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

public_bp = Blueprint("public", __name__)   # public storefront
admin_bp  = Blueprint("admin",  __name__)   # admin panel
auth_bp   = Blueprint("auth",   __name__)   # login / logout
api_bp    = Blueprint("api",    __name__)   # JSON API endpoints
user_bp   = Blueprint("user",   __name__)   # user accounts and shopping


# ══════════════════════════════════════════════════════════════════════════════
#  PRIVATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_item_form() -> tuple[bool, list, list]:
    """
    Parse the colors / images fields that appear identically on both the
    create-item and edit-item forms.  Returns (colors_enabled, colors, images).
    """
    colors_enabled = request.form.get("colors_enabled") == "1"
    try:
        colors = json.loads(request.form.get("colors_json", "[]"))
    except (json.JSONDecodeError, ValueError):
        colors = []
    try:
        images = [
            u.strip()
            for u in json.loads(request.form.get("images_json", "[]"))
            if isinstance(u, str) and u.strip()
        ]
    except (json.JSONDecodeError, ValueError):
        images = []
    return colors_enabled, colors, images


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@public_bp.route("/")
def index():
    """Main storefront — shows all products with optional filter/search."""
    category = request.args.get("category", "")
    search   = request.args.get("search",   "")

    items      = get_all_items(category=category, search=search)
    categories = get_all_categories()

    return render_template(
        "index.html",
        items=items,
        categories=categories,
        selected_category=category,
        search=search,
    )


@public_bp.route("/about")
def about():
    return render_template("about.html")


@public_bp.route("/item/<item_id>")
def item_detail(item_id):
    """Single product detail page."""
    item = get_item_by_id(item_id)
    if not item:
        return render_template("404.html"), 404
    record_item_view(item_id, session.get("user_id"))
    return render_template("item_detail.html", item=item)


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES  (login / logout)
# ══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """
    GET  → show the login form
    POST → validate the password, set session, redirect to dashboard
    """
    error = None

    if request.method == "POST":
        entered = request.form.get("password", "")

        if check_password(entered):
            session["admin_logged_in"] = True
            session["admin_last_seen"] = datetime.now(timezone.utc).isoformat()
            return redirect(url_for("admin.dashboard"))

        error = "Incorrect password. Please try again."

    return render_template("admin_login.html", error=error)


@auth_bp.route("/admin/logout")
def admin_logout():
    """Clear the admin session and return to the storefront."""
    session.pop("admin_logged_in", None)
    session.pop("admin_last_seen", None)
    return redirect(url_for("public.index"))


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/admin")
@login_required
def dashboard():
    """
    Admin dashboard — inventory table with all items, stats, and low-stock alerts.
    Protected by @login_required: redirects to login if not authenticated.
    """
    items = get_all_items()

    total_items = len(items)
    total_stock = sum(item.get("stock", 0) for item in items)
    low_stock   = [item for item in items if item.get("stock", 0) <= 5]

    return render_template(
        "admin_dashboard.html",
        items=items,
        total_items=total_items,
        total_stock=total_stock,
        low_stock=low_stock,
    )


@admin_bp.route("/admin/item/new", methods=["GET", "POST"])
@login_required
def new_item():
    """
    GET  → show empty create-item form
    POST → read form data, create item in DB, redirect to dashboard
    """
    if request.method == "POST":
        colors_enabled, colors, images = _parse_item_form()

        create_item(
            name           = request.form.get("name", "").strip(),
            description    = request.form.get("description", "").strip(),
            category_id    = request.form.get("category_id", "").strip(),
            price          = float(request.form.get("price", 0)),
            stock          = int(request.form.get("stock", 0)),
            image_url      = request.form.get("image_url", "").strip(),
            colors_enabled = colors_enabled,
            colors         = colors,
            images         = images,
            cost           = float(request.form.get("cost", 0) or 0),
        )
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_item_form.html", item=None, action="Create")


@admin_bp.route("/admin/item/edit/<item_id>", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    """
    GET  → show edit form pre-filled with existing item data
    POST → update item in DB, redirect to dashboard
    """
    item = get_item_by_id(item_id)
    if not item:
        return "Item not found", 404

    if request.method == "POST":
        colors_enabled, colors, images = _parse_item_form()

        update_item(
            item_id        = item_id,
            name           = request.form.get("name", "").strip(),
            description    = request.form.get("description", "").strip(),
            category_id    = request.form.get("category_id", "").strip(),
            price          = float(request.form.get("price", 0)),
            stock          = int(request.form.get("stock", 0)),
            image_url      = request.form.get("image_url", "").strip(),
            colors_enabled = colors_enabled,
            colors         = colors,
            images         = images,
            cost           = float(request.form.get("cost", 0) or 0),
        )
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_item_form.html", item=item, action="Update")


@admin_bp.route("/admin/item/refresh-image/<item_id>", methods=["POST"])
@login_required
def refresh_image(item_id):
    """Fetch a fresh image for an existing item and save it."""
    item = get_item_by_id(item_id)
    if not item:
        return "Item not found", 404
    new_url = fetch_image(item["name"], item.get("description", ""))
    update_item(item_id, item["name"], item.get("description", ""),
                item.get("category_id", ""), item["price"], item["stock"], new_url,
                colors_enabled=item.get("colors_enabled", False),
                colors=item.get("colors", []),
                images=item.get("images", []),
                cost=item.get("cost", 0.0))
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/item/delete/<item_id>", methods=["POST"])
@login_required
def delete_item_route(item_id):
    """Delete an item by ID and return to the dashboard."""
    delete_item(item_id)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/item/sale/<item_id>", methods=["GET", "POST"])
@login_required
def manage_sale(item_id):
    item = get_item_by_id(item_id)
    if not item:
        return render_template("404.html"), 404

    sale_info = get_sale_info(item)
    item.update(sale_info)

    if request.method == "POST":
        action = request.form.get("action", "set")
        if action == "clear":
            clear_item_sale(item_id)
        else:
            sale_type  = request.form.get("sale_type", "percentage")
            sale_value = float(request.form.get("sale_value") or 0)

            if sale_value > 0:
                set_item_sale(item_id, sale_type, sale_value,
                              sale_start=_sale_dt_from_form(request.form.get("sale_start")),
                              sale_end=_sale_dt_from_form(request.form.get("sale_end")))
        return redirect(url_for("admin.dashboard"))

    sale_start_str = _sale_dt_to_form(item.get("sale_start"))
    sale_end_str   = _sale_dt_to_form(item.get("sale_end"))
    return render_template("admin_sale_form.html", item=item,
                           sale_start_str=sale_start_str, sale_end_str=sale_end_str)


# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (JSON responses)
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route("/api/fetch-image")
@login_required
def api_fetch_image():
    name        = request.args.get("name", "")
    description = request.args.get("description", "")
    image_url   = fetch_image(name, description)
    return jsonify({"image_url": image_url})


@api_bp.route("/api/fetch-images")
@login_required
def api_fetch_images():
    name        = request.args.get("name", "")
    description = request.args.get("description", "")
    images      = fetch_images(name, description, count=6)
    return jsonify({"images": images})


@api_bp.route("/api/categories", methods=["GET"])
@login_required
def api_get_categories():
    """Return all categories as [{id, name}] sorted by name."""
    return jsonify(get_all_categories_with_ids())


@api_bp.route("/api/categories", methods=["POST"])
@login_required
def api_create_category():
    """
    Case-insensitive find-or-create a category.
    Body: { "name": "..." }
    Returns: { "id": "...", "name": "..." }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    category = get_or_create_category(name)
    return jsonify(category), 201


# ══════════════════════════════════════════════════════════════════════════════
#  USER ROUTES  (registration, login, cart, checkout, account)
# ══════════════════════════════════════════════════════════════════════════════

@user_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    GET  → show registration form
    POST → create user account, send verification email
    """
    error = None

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # Validation
        if not email or not password:
            error = "Email and password are required."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif get_user_by_email(email):
            error = "An account with this email already exists."
        else:
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            create_user(email, password_hash)
            # Re-fetch to get the verification_token that create_user generated
            user = get_user_by_email(email)
            send_verification_email(email, user["verification_token"])

            return render_template("verification_sent.html", email=email)

    return render_template("user_register.html", error=error)


@user_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    GET  → show login form
    POST → authenticate user, set session
    """
    error = None

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        user = get_user_by_email(email)

        if not user:
            error = "Invalid email or password."
        elif not user.get("is_verified"):
            error = "Please verify your email address before logging in."
        else:
            if bcrypt.check_password_hash(user["password_hash"], password):
                session["user_id"] = user["_id"]
                next_url = request.args.get("next", "")
                # Only allow safe relative redirects (prevents open-redirect via ?next=//evil.com)
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("public.index"))
            else:
                error = "Invalid email or password."

    return render_template("user_login.html", error=error)


@user_bp.route("/logout")
def logout():
    """Clear user session and redirect to home."""
    session.pop("user_id", None)
    session.pop("cart", None)
    return redirect(url_for("public.index"))


@user_bp.route("/verify-email/<token>")
def verify_email(token):
    """
    Verify user's email address using the token from the email link.
    """
    success = verify_user_email(token)

    if success:
        return render_template("verify_email.html", success=True)
    else:
        return render_template("verify_email.html", success=False,
                               error="Invalid or expired verification link.")


# ── Cart Routes ────────────────────────────────────────────────────────────────

@user_bp.route("/cart")
def view_cart():
    """Show shopping cart."""
    cart = get_cart()

    # Attach current stock so the template can warn when cart quantity exceeds available stock
    for cart_item in cart:
        item = get_item_by_id(cart_item["item_id"])
        if item:
            cart_item["available_stock"] = item.get("stock", 0)
        else:
            cart_item["available_stock"] = 0

    totals = get_cart_total()
    return render_template("cart.html", cart=cart, totals=totals)


@user_bp.route("/cart/add", methods=["POST"])
def add_to_cart_route():
    """Add item to cart (AJAX endpoint)."""
    item_id = request.form.get("item_id")
    quantity = int(request.form.get("quantity", 1))
    selected_color = request.form.get("selected_color")

    result = cart_add(item_id, quantity, selected_color)

    if result["success"]:
        totals = get_cart_total()
        return jsonify({
            "success": True,
            "item_count": totals["item_count"],
            "message": result.get("message", "Added to cart")
        })
    else:
        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to add item")
        }), 400


@user_bp.route("/cart/remove/<item_id>", methods=["POST"])
def remove_from_cart_route(item_id):
    """Remove item from cart."""
    selected_color = request.form.get("selected_color")
    remove_from_cart(item_id, selected_color)
    return redirect(url_for("user.view_cart"))


@user_bp.route("/cart/update", methods=["POST"])
def update_cart_route():
    """Update item quantity in cart."""
    item_id = request.form.get("item_id")
    quantity = int(request.form.get("quantity", 1))
    selected_color = request.form.get("selected_color")

    result = update_cart_quantity(item_id, quantity, selected_color)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes['application/json']:
        if result["success"]:
            totals = get_cart_total()
            return jsonify({
                "success": True,
                "totals": totals,
                "message": result.get("message", "Cart updated")
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Update failed")
            }), 400
    else:
        return redirect(url_for("user.view_cart"))


# ── Checkout Routes ────────────────────────────────────────────────────────────

@user_bp.route("/checkout", methods=["GET", "POST"])
@user_login_required
def checkout():
    """
    GET  → show checkout form
    POST → create order, clear cart, redirect to confirmation
    """
    cart = get_cart()
    totals = get_cart_total()

    if not cart:
        return redirect(url_for("user.view_cart"))

    # Check stock on GET so the user sees problems before filling in address.
    # The same check runs again on POST to catch concurrent depletions.
    stock_validation = validate_cart_stock()
    if not stock_validation["valid"]:
        error_message = "Some items in your cart are no longer available or have insufficient stock:<br>"
        for issue in stock_validation["issues"]:
            error_message += f"• {issue['name']}: {issue['issue']}<br>"
        return render_template("cart.html", cart=cart, totals=totals, error=error_message)

    if request.method == "POST":
        stock_validation = validate_cart_stock()
        if not stock_validation["valid"]:
            error_message = "Some items are no longer available in the requested quantity. Please review your cart."
            return render_template("checkout.html", cart=cart, totals=totals, error=error_message)

        shipping_address = {
            "name": request.form.get("name", "").strip(),
            "address": request.form.get("address", "").strip(),
            "city": request.form.get("city", "").strip(),
            "state": request.form.get("state", "").strip(),
            "zip": request.form.get("zip", "").strip(),
            "country": request.form.get("country", "USA").strip(),
        }

        if not all([shipping_address["name"], shipping_address["address"],
                    shipping_address["city"], shipping_address["state"], shipping_address["zip"]]):
            error = "All shipping address fields are required."
            return render_template("checkout.html", cart=cart, totals=totals, error=error)

        order_number = generate_order_number()
        user_id = session["user_id"]
        order_id = create_order(user_id, cart, shipping_address, order_number)

        for cart_item in cart:
            decrement_stock(cart_item["item_id"], cart_item["quantity"])

        user = get_current_user()
        order = get_order_by_id(order_id)
        send_order_confirmation(user["email"], order)

        clear_cart()

        return redirect(url_for("user.order_confirmation", order_id=order_id))

    return render_template("checkout.html", cart=cart, totals=totals)


@user_bp.route("/order/<order_id>")
@user_login_required
def order_confirmation(order_id):
    """Show order confirmation page."""
    order = get_order_by_id(order_id)
    if not order:
        return "Order not found", 404

    if order["user_id"] != session["user_id"]:
        return "Unauthorized", 403

    return render_template("order_confirmation.html", order=order)


# ── User Account Routes ────────────────────────────────────────────────────────

@user_bp.route("/account")
@user_login_required
def account():
    """User account dashboard with recent orders."""
    user = get_current_user()
    orders = get_user_orders(user["_id"])
    return render_template("user_account.html", user=user, orders=orders[:5])


@user_bp.route("/orders")
@user_login_required
def order_history():
    """Full order history for current user."""
    user = get_current_user()
    orders = get_user_orders(user["_id"])
    return render_template("user_account.html", user=user, orders=orders)


@user_bp.route("/orders/<order_id>")
@user_login_required
def order_detail(order_id):
    """Single order detail view."""
    order = get_order_by_id(order_id)
    if not order:
        return "Order not found", 404

    if order["user_id"] != session["user_id"]:
        return "Unauthorized", 403

    return render_template("order_detail.html", order=order)


# ── Admin User Management Routes (added to admin blueprint) ────────────────────

@admin_bp.route("/admin/analytics")
@login_required
def admin_analytics():
    """Charts dashboard — sales, popularity, views, top users, etc."""
    return render_template("admin_analytics.html", data=dashboard_payload())


@admin_bp.route("/admin/users")
@login_required
def admin_users():
    """Admin view of all users with statistics."""
    users = get_all_users_with_stats()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/admin/users/<user_id>")
@login_required
def admin_user_detail(user_id):
    """Admin view of single user with full order history."""
    user = get_user_by_id(user_id)
    if not user:
        return "User not found", 404

    orders = get_user_orders(user_id)
    total_spent = sum(order.get("total", 0) for order in orders)

    return render_template("admin_user_detail.html", user=user, orders=orders, total_spent=total_spent)


@admin_bp.route("/admin/users/new", methods=["GET", "POST"])
@login_required
def admin_add_user():
    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        is_verified = request.form.get("is_verified") == "1"

        if not email or not password:
            error = "Email and password are required."
        elif get_user_by_email(email):
            error = "A user with this email already exists."
        else:
            password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            user_id = create_user(email, password_hash)
            if is_verified:
                update_user(user_id, email, is_verified=True)
            return redirect(url_for("admin.admin_users"))

    return render_template("admin_user_form.html", action="Add", user=None, error=error)


@admin_bp.route("/admin/users/<user_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return "User not found", 404

    error = None
    if request.method == "POST":
        email       = request.form.get("email", "").strip().lower()
        password    = request.form.get("password", "").strip()
        is_verified = request.form.get("is_verified") == "1"

        if not email:
            error = "Email is required."
        else:
            password_hash = None
            if password:
                password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            update_user(user_id, email, password_hash=password_hash, is_verified=is_verified)
            return redirect(url_for("admin.admin_users"))

    return render_template("admin_user_form.html", action="Edit", user=user, error=error)


@admin_bp.route("/admin/users/<user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    delete_user(user_id)
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/admin/orders")
@login_required
def admin_orders():
    """Admin view of all orders across all users."""
    orders = get_all_orders()
    return render_template("admin_orders.html", orders=orders)


@admin_bp.route("/admin/orders/<order_id>/status", methods=["POST"])
@login_required
def admin_update_order_status(order_id):
    from user_models import update_order_status
    from email_service import send_order_status_update
    status = request.form.get("status", "").strip()
    if status in ("pending", "confirmed", "shipped", "delivered"):
        order = update_order_status(order_id, status)
        if order:
            try:
                send_order_status_update(order["user_email"], order)
            except Exception:
                logger.error(
                    "admin_update_order_status: failed to send status email for order %s to %s",
                    order_id, order["user_email"], exc_info=True,
                )
    return redirect(url_for("admin.admin_orders"))