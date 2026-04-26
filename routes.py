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

from auth   import login_required, check_password   # auth helpers
from models import (                                 # data-layer functions
    get_all_items, get_item_by_id, get_all_categories,
    create_item, update_item, delete_item, fetch_image
)


# ══════════════════════════════════════════════════════════════════════════════
#  BLUEPRINT DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

public_bp = Blueprint("public", __name__)   # public storefront
admin_bp  = Blueprint("admin",  __name__)   # admin panel
auth_bp   = Blueprint("auth",   __name__)   # login / logout
api_bp    = Blueprint("api",    __name__)   # JSON API endpoints


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
        create_item(                                           # delegate to models.py
            name        = request.form.get("name", "").strip(),
            description = request.form.get("description", "").strip(),
            category    = request.form.get("category", "").strip(),
            price       = float(request.form.get("price", 0)),
            stock       = int(request.form.get("stock", 0)),
            image_url   = request.form.get("image_url", "").strip(),
        )
        return redirect(url_for("admin.dashboard"))  # back to dashboard after save

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
        update_item(                                           # delegate to models.py
            item_id     = item_id,
            name        = request.form.get("name", "").strip(),
            description = request.form.get("description", "").strip(),
            category    = request.form.get("category", "").strip(),
            price       = float(request.form.get("price", 0)),
            stock       = int(request.form.get("stock", 0)),
            image_url   = request.form.get("image_url", "").strip(),
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
