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

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, jsonify
)
import json

from auth   import login_required, check_password
from models import (
    get_all_items, get_item_by_id, get_all_categories,
    create_item, update_item, delete_item, fetch_image
)
from user_auth import user_login_required, get_current_user
from user_models import (
    create_user, get_user_by_email, verify_user_email,
    get_user_orders, get_order_by_id, create_order,
    get_all_users_with_stats, get_all_orders
)
from cart_helpers import (
    add_to_cart as cart_add, remove_from_cart,
    update_cart_quantity, get_cart, get_cart_total, clear_cart,
    validate_cart_stock
)
from email_service import send_verification_email, send_order_confirmation
from order_generator import generate_order_number


# ══════════════════════════════════════════════════════════════════════════════
#  BLUEPRINT DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

public_bp = Blueprint("public", __name__)   # public storefront
admin_bp  = Blueprint("admin",  __name__)   # admin panel
auth_bp   = Blueprint("auth",   __name__)   # login / logout
api_bp    = Blueprint("api",    __name__)   # JSON API endpoints
user_bp   = Blueprint("user",   __name__)   # user accounts and shopping


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@public_bp.route("/")
def index():
    """Main storefront — shows all products with optional filter/search."""
    category = request.args.get("category", "")  # e.g. ?category=Cables
    search   = request.args.get("search",   "")  # e.g. ?search=usb

    items      = get_all_items(category=category, search=search)  # fetch from DB
    categories = get_all_categories()                             # for filter pills

    return render_template(
        "index.html",
        items=items,
        categories=categories,
        selected_category=category,
        search=search,
    )


@public_bp.route("/item/<item_id>")
def item_detail(item_id):
    """Single product detail page."""
    item = get_item_by_id(item_id)  # fetch one item by ID
    if not item:
        return render_template("404.html"), 404  # show friendly 404 page
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
        entered = request.form.get("password", "")  # read submitted password

        if check_password(entered):                        # validate in auth.py
            session["admin_logged_in"] = True              # mark session as authenticated
            return redirect(url_for("admin.dashboard"))    # go to admin dashboard

        error = "Incorrect password. Please try again."   # wrong password message

    return render_template("admin_login.html", error=error)


@auth_bp.route("/admin/logout")
def admin_logout():
    """Clear the admin session and return to the storefront."""
    session.pop("admin_logged_in", None)  # remove the session flag
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
    items = get_all_items()  # fetch everything (no filters)

    total_items = len(items)
    total_stock = sum(item.get("stock", 0) for item in items)       # sum all stock values
    low_stock   = [item for item in items if item.get("stock", 0) <= 5]  # flag low items

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
        colors_enabled = request.form.get("colors_enabled") == "1"
        try:
            colors = json.loads(request.form.get("colors_json", "[]"))
        except (json.JSONDecodeError, ValueError):
            colors = []  # fallback to empty list if JSON is invalid

        create_item(
            name           = request.form.get("name", "").strip(),
            description    = request.form.get("description", "").strip(),
            category       = request.form.get("category", "").strip(),
            price          = float(request.form.get("price", 0)),
            stock          = int(request.form.get("stock", 0)),
            image_url      = request.form.get("image_url", "").strip(),
            colors_enabled = colors_enabled,
            colors         = colors,
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
    item = get_item_by_id(item_id)  # load existing item
    if not item:
        return "Item not found", 404

    if request.method == "POST":
        colors_enabled = request.form.get("colors_enabled") == "1"
        try:
            colors = json.loads(request.form.get("colors_json", "[]"))
        except (json.JSONDecodeError, ValueError):
            colors = []  # fallback to empty list if JSON is invalid

        update_item(
            item_id        = item_id,
            name           = request.form.get("name", "").strip(),
            description    = request.form.get("description", "").strip(),
            category       = request.form.get("category", "").strip(),
            price          = float(request.form.get("price", 0)),
            stock          = int(request.form.get("stock", 0)),
            image_url      = request.form.get("image_url", "").strip(),
            colors_enabled = colors_enabled,
            colors         = colors,
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
                item.get("category", ""), item["price"], item["stock"], new_url)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/item/delete/<item_id>", methods=["POST"])
@login_required
def delete_item_route(item_id):
    """Delete an item by ID and return to the dashboard."""
    delete_item(item_id)                     # delegate to models.py
    return redirect(url_for("admin.dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (JSON responses)
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route("/api/fetch-image")
@login_required
def api_fetch_image():
    """
    AJAX endpoint used by the admin form's "Auto-fetch" button.
    Calls Unsplash (or fallback) and returns the image URL as JSON.

    Query params:
        name        — product name
        description — product description

    Response:
        { "image_url": "https://..." }
    """
    name        = request.args.get("name", "")
    description = request.args.get("description", "")
    image_url   = fetch_image(name, description)       # from models.py
    return jsonify({"image_url": image_url})


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
            # Create user with hashed password
            from app import bcrypt
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            user_id = create_user(email, password_hash)

            # Get the user to retrieve the verification token
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
            # Check password
            from app import bcrypt
            if bcrypt.check_password_hash(user["password_hash"], password):
                session["user_id"] = user["_id"]  # log user in
                return redirect(url_for("public.index"))
            else:
                error = "Invalid email or password."

    return render_template("user_login.html", error=error)


@user_bp.route("/logout")
def logout():
    """Clear user session and redirect to home."""
    session.pop("user_id", None)
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

    # Add stock info to each cart item
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

    # Check if this is an AJAX request
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
        # Regular form submission - redirect back to cart
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
        return redirect(url_for("user.view_cart"))  # can't checkout with empty cart

    # Validate stock before showing checkout or processing order
    stock_validation = validate_cart_stock()
    if not stock_validation["valid"]:
        error_message = "Some items in your cart are no longer available or have insufficient stock:<br>"
        for issue in stock_validation["issues"]:
            error_message += f"• {issue['name']}: {issue['issue']}<br>"
        return render_template("cart.html", cart=cart, totals=totals, error=error_message)

    if request.method == "POST":
        # Double-check stock again before creating order
        stock_validation = validate_cart_stock()
        if not stock_validation["valid"]:
            error_message = "Some items are no longer available in the requested quantity. Please review your cart."
            return render_template("checkout.html", cart=cart, totals=totals, error=error_message)

        # Get shipping address from form
        shipping_address = {
            "name": request.form.get("name", "").strip(),
            "address": request.form.get("address", "").strip(),
            "city": request.form.get("city", "").strip(),
            "state": request.form.get("state", "").strip(),
            "zip": request.form.get("zip", "").strip(),
            "country": request.form.get("country", "USA").strip(),
        }

        # Validate required fields
        if not all([shipping_address["name"], shipping_address["address"],
                    shipping_address["city"], shipping_address["state"], shipping_address["zip"]]):
            error = "All shipping address fields are required."
            return render_template("checkout.html", cart=cart, totals=totals, error=error)

        # Create order
        order_number = generate_order_number()
        user_id = session["user_id"]
        order_id = create_order(user_id, cart, shipping_address, order_number)

        # Send confirmation email
        user = get_current_user()
        order = get_order_by_id(order_id)
        send_order_confirmation(user["email"], order)

        # Clear cart
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

    # Verify this order belongs to the current user
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
    return render_template("user_account.html", user=user, orders=orders[:5])  # show 5 most recent


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

    # Verify this order belongs to the current user
    if order["user_id"] != session["user_id"]:
        return "Unauthorized", 403

    return render_template("order_detail.html", order=order)


# ── Admin User Management Routes (added to admin blueprint) ────────────────────

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
    from user_models import get_user_by_id
    user = get_user_by_id(user_id)
    if not user:
        return "User not found", 404

    orders = get_user_orders(user_id)
    total_spent = sum(order.get("total", 0) for order in orders)

    return render_template("admin_user_detail.html", user=user, orders=orders, total_spent=total_spent)


@admin_bp.route("/admin/orders")
@login_required
def admin_orders():
    """Admin view of all orders across all users."""
    orders = get_all_orders()
    return render_template("admin_orders.html", orders=orders)
