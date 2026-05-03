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
import html
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app import limiter

JERUSALEM_TZ = ZoneInfo("Asia/Jerusalem")


def _sale_dt_from_form(s: str) -> datetime | None:
    """Parse a datetime-local string as Jerusalem time and return a naive UTC datetime."""
    if not s:
        return None
    try:
        return (datetime.fromisoformat(s)
                .replace(tzinfo=JERUSALEM_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None))
    except (ValueError, TypeError):
        return None


def _sale_dt_to_form(dt: datetime) -> str:
    """Convert a naive UTC datetime to a Jerusalem-time datetime-local string."""
    if not dt:
        return ""
    return (dt.replace(tzinfo=timezone.utc)
              .astimezone(JERUSALEM_TZ)
              .strftime("%Y-%m-%dT%H:%M"))

from auth   import login_required, check_password
from models import (
    get_all_items, get_item_by_id, get_all_categories,
    get_all_categories_with_ids, get_or_create_category,
    create_item, update_item, delete_item, fetch_image, fetch_images, decrement_stock,
    set_item_sale, clear_item_sale
)
from user_auth import user_login_required, get_current_user
from user_models import (
    create_user, get_user_by_email, verify_user_email,
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
    """
    Storefront — browse all products.
    ---
    tags:
      - Storefront
    summary: Product listing page
    parameters:
      - name: category
        in: query
        type: string
        required: false
        description: Filter by category name (e.g. "Cables")
      - name: search
        in: query
        type: string
        required: false
        description: Full-text search across name and description
    responses:
      200:
        description: HTML product grid with optional filters applied
    """
    category = request.args.get("category", "")
    search   = request.args.get("search",   "")

    items      = get_all_items(category=category, search=search)
    categories = get_all_categories()

    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    for item in items:
        created = item.get("created_at")
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            item["is_new"] = created > threshold
        else:
            item["is_new"] = False

    return render_template(
        "index.html",
        items=items,
        categories=categories,
        selected_category=category,
        search=search,
    )


@public_bp.route("/about")
def about():
    """
    About page.
    ---
    tags:
      - Storefront
    summary: About TechDen
    responses:
      200:
        description: HTML about page
    """
    return render_template("about.html")


@public_bp.route("/item/<item_id>")
def item_detail(item_id):
    """
    Single product detail page.
    ---
    tags:
      - Storefront
    summary: Product detail
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product
    responses:
      200:
        description: HTML product detail page
      404:
        description: Product not found
    """
    item = get_item_by_id(item_id)
    if not item:
        return render_template("404.html"), 404
    record_item_view(item_id, session.get("user_id"))
    return render_template("item_detail.html", item=item)


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES  (login / logout)
# ══════════════════════════════════════════════════════════════════════════════

@auth_bp.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    """
    Admin login.
    ---
    tags:
      - Admin Auth
    summary: Admin login form and session creation
    description: |
      GET returns the login form. POST validates the admin password and
      creates a session with a 5-minute inactivity timeout.
      **Rate limited:** 5 requests/minute per IP.
    parameters:
      - name: body
        in: formData
        required: false
        description: Required only for POST
      - name: password
        in: formData
        type: string
        required: false
        description: Admin password (set via ADMIN_PASSWORD env var)
    responses:
      200:
        description: Login form (GET) or form with error message (POST on bad password)
      302:
        description: Redirect to /admin on successful login
      429:
        description: Too many requests — rate limit exceeded
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
    """
    Admin logout.
    ---
    tags:
      - Admin Auth
    summary: Destroy admin session
    responses:
      302:
        description: Redirect to storefront
    """
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
    Admin dashboard.
    ---
    tags:
      - Admin – Items
    summary: Inventory overview with stats and low-stock alerts
    description: Requires an active admin session (5-minute inactivity timeout).
    responses:
      200:
        description: HTML dashboard with item table, stock stats, and sale status
      302:
        description: Redirect to /admin/login if not authenticated or session expired
    """
    items = get_all_items()

    total_items = len(items)
    total_stock = sum(item.get("stock", 0) for item in items)
    low_stock   = [item for item in items if item.get("stock", 0) <= 5]
    on_sale     = [item for item in items if item.get("sale_active") or item.get("sale_scheduled")]

    return render_template(
        "admin_dashboard.html",
        items=items,
        total_items=total_items,
        total_stock=total_stock,
        low_stock=low_stock,
        on_sale=on_sale,
    )


@admin_bp.route("/admin/item/new", methods=["GET", "POST"])
@login_required
def new_item():
    """
    Create a new product.
    ---
    tags:
      - Admin – Items
    summary: Create product (form + submit)
    description: |
      GET returns a blank item form. POST creates the item in MongoDB.
      If `image_url` is omitted, an image is auto-fetched via Unsplash / DuckDuckGo.
      Requires admin session.
    parameters:
      - name: name
        in: formData
        type: string
        required: true
        description: Product name
      - name: description
        in: formData
        type: string
        required: false
        description: Product description
      - name: category_id
        in: formData
        type: string
        required: false
        description: Category ObjectId (from GET /api/categories)
      - name: price
        in: formData
        type: number
        required: true
        description: Retail price in USD
      - name: cost
        in: formData
        type: number
        required: false
        description: Cost / wholesale price in USD
      - name: stock
        in: formData
        type: integer
        required: true
        description: Units in stock
      - name: image_url
        in: formData
        type: string
        required: false
        description: Primary image URL (auto-fetched if blank)
      - name: images_json
        in: formData
        type: string
        required: false
        description: JSON array of additional image URLs
      - name: colors_enabled
        in: formData
        type: string
        required: false
        description: Set to "1" to enable color variants
      - name: colors_json
        in: formData
        type: string
        required: false
        description: JSON array of color objects e.g. [{"name":"Red","hex":"#ff0000"}]
      - name: sale_type
        in: formData
        type: string
        required: false
        description: "One of: percentage | amount | target_price"
      - name: sale_value
        in: formData
        type: number
        required: false
        description: Sale value (percent off, amount off, or target price)
      - name: sale_start
        in: formData
        type: string
        required: false
        description: Sale start (datetime-local string, Jerusalem time)
      - name: sale_end
        in: formData
        type: string
        required: false
        description: Sale end (datetime-local string, Jerusalem time)
    responses:
      200:
        description: HTML create-item form (GET)
      302:
        description: Redirect to /admin on success (POST)
    """
    if request.method == "POST":
        colors_enabled = request.form.get("colors_enabled") == "1"
        try:
            colors = json.loads(request.form.get("colors_json", "[]"))
        except (json.JSONDecodeError, ValueError):
            colors = []
        try:
            images = [u.strip() for u in json.loads(request.form.get("images_json", "[]")) if isinstance(u, str) and u.strip()]
        except (json.JSONDecodeError, ValueError):
            images = []

        sale_start = _sale_dt_from_form(request.form.get("sale_start", "").strip())
        sale_end   = _sale_dt_from_form(request.form.get("sale_end",   "").strip())

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
            sale_type      = request.form.get("sale_type", "").strip(),
            sale_value     = float(request.form.get("sale_value") or 0),
            sale_start     = sale_start,
            sale_end       = sale_end,
        )
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_item_form.html", item=None, action="Create",
                           sale_start_str="", sale_end_str="")


@admin_bp.route("/admin/item/edit/<item_id>", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    """
    Edit an existing product.
    ---
    tags:
      - Admin – Items
    summary: Edit product (form + submit)
    description: |
      GET returns the pre-filled edit form. POST saves the updated item.
      Accepts the same fields as POST /admin/item/new.
      Requires admin session.
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product to edit
      - name: name
        in: formData
        type: string
        required: false
      - name: description
        in: formData
        type: string
        required: false
      - name: category_id
        in: formData
        type: string
        required: false
      - name: price
        in: formData
        type: number
        required: false
      - name: cost
        in: formData
        type: number
        required: false
      - name: stock
        in: formData
        type: integer
        required: false
      - name: image_url
        in: formData
        type: string
        required: false
      - name: images_json
        in: formData
        type: string
        required: false
      - name: colors_enabled
        in: formData
        type: string
        required: false
      - name: colors_json
        in: formData
        type: string
        required: false
      - name: sale_type
        in: formData
        type: string
        required: false
      - name: sale_value
        in: formData
        type: number
        required: false
      - name: sale_start
        in: formData
        type: string
        required: false
      - name: sale_end
        in: formData
        type: string
        required: false
    responses:
      200:
        description: HTML edit form pre-filled with current values (GET)
      302:
        description: Redirect to /admin on success (POST)
      404:
        description: Product not found
    """
    item = get_item_by_id(item_id)
    if not item:
        return "Item not found", 404

    if request.method == "POST":
        colors_enabled = request.form.get("colors_enabled") == "1"
        try:
            colors = json.loads(request.form.get("colors_json", "[]"))
        except (json.JSONDecodeError, ValueError):
            colors = []
        try:
            images = [u.strip() for u in json.loads(request.form.get("images_json", "[]")) if isinstance(u, str) and u.strip()]
        except (json.JSONDecodeError, ValueError):
            images = []

        sale_start = _sale_dt_from_form(request.form.get("sale_start", "").strip())
        sale_end   = _sale_dt_from_form(request.form.get("sale_end",   "").strip())

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
            sale_type      = request.form.get("sale_type", "").strip(),
            sale_value     = float(request.form.get("sale_value") or 0),
            sale_start     = sale_start,
            sale_end       = sale_end,
        )
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_item_form.html", item=item, action="Update",
                           sale_start_str=_sale_dt_to_form(item.get("sale_start")),
                           sale_end_str=_sale_dt_to_form(item.get("sale_end")))


@admin_bp.route("/admin/item/refresh-image/<item_id>", methods=["POST"])
@login_required
def refresh_image(item_id):
    """
    Re-fetch a product image.
    ---
    tags:
      - Admin – Items
    summary: Auto-fetch a new image for an existing product
    description: |
      Runs the image-fetch cascade (Unsplash → DuckDuckGo → picsum) and saves the
      first result as the product's primary image. Requires admin session.
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product
    responses:
      302:
        description: Redirect to /admin on success
      404:
        description: Product not found
    """
    item = get_item_by_id(item_id)
    if not item:
        return "Item not found", 404
    new_url = fetch_image(item["name"], item.get("description", ""))
    update_item(item_id, item["name"], item.get("description", ""),
                item.get("category_id", ""), item["price"], item["stock"], new_url,
                colors_enabled=item.get("colors_enabled", False),
                colors=item.get("colors", []),
                images=item.get("images", []),
                cost=item.get("cost", 0.0),
                sale_type=item.get("sale_type", ""),
                sale_value=item.get("sale_value", 0.0),
                sale_start=item.get("sale_start"),
                sale_end=item.get("sale_end"))
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/item/delete/<item_id>", methods=["POST"])
@login_required
def delete_item_route(item_id):
    """
    Delete a product.
    ---
    tags:
      - Admin – Items
    summary: Permanently delete a product
    description: Requires admin session. This action is irreversible.
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product to delete
    responses:
      302:
        description: Redirect to /admin on success
    """
    delete_item(item_id)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/item/sale/<item_id>", methods=["GET", "POST"])
@login_required
def manage_sale(item_id):
    """
    Manage a product sale.
    ---
    tags:
      - Admin – Sales
    summary: Set or clear a sale on a product
    description: |
      GET shows the sale configuration form. POST applies or clears the sale.
      Sale times are entered in Jerusalem time (Asia/Jerusalem) and stored as naive UTC.
      Requires admin session.
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product
      - name: action
        in: formData
        type: string
        required: false
        description: Set to "clear" to remove any active sale
      - name: sale_type
        in: formData
        type: string
        required: false
        description: "One of: percentage | amount | target_price"
      - name: sale_value
        in: formData
        type: number
        required: false
        description: Sale value (ignored when action=clear)
      - name: sale_start
        in: formData
        type: string
        required: false
        description: Sale start datetime-local (Jerusalem time). Omit for immediate.
      - name: sale_end
        in: formData
        type: string
        required: false
        description: Sale end datetime-local (Jerusalem time). Omit for no expiry.
    responses:
      200:
        description: HTML sale form (GET)
      302:
        description: Redirect to /admin on submit (POST)
      404:
        description: Product not found
    """
    item = get_item_by_id(item_id)
    if not item:
        return "Item not found", 404

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "clear":
            clear_item_sale(item_id)
        else:
            sale_type  = request.form.get("sale_type", "").strip()
            sale_value = float(request.form.get("sale_value") or 0)
            sale_start = _sale_dt_from_form(request.form.get("sale_start", "").strip())
            sale_end   = _sale_dt_from_form(request.form.get("sale_end",   "").strip())
            if sale_type in ("percentage", "amount", "target_price") and sale_value > 0:
                set_item_sale(item_id, sale_type, sale_value, sale_start, sale_end)
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_sale_form.html", item=item,
                           sale_start_str=_sale_dt_to_form(item.get("sale_start")),
                           sale_end_str=_sale_dt_to_form(item.get("sale_end")))


# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (JSON responses)
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route("/api/fetch-image")
@login_required
def api_fetch_image():
    """
    Fetch a single product image URL.
    ---
    tags:
      - Images API
    summary: Auto-fetch one image for a product
    description: |
      Runs the image cascade: Unsplash (if key set) → DuckDuckGo → picsum.photos.
      Returns the first result. Requires admin session.
    parameters:
      - name: name
        in: query
        type: string
        required: true
        description: Product name used as search query
      - name: description
        in: query
        type: string
        required: false
        description: Product description for additional search context
    responses:
      200:
        description: Image URL
        schema:
          type: object
          properties:
            image_url:
              type: string
              example: "https://images.unsplash.com/photo-abc123?w=640"
      302:
        description: Redirect to /admin/login if not authenticated
    """
    name        = request.args.get("name", "")
    description = request.args.get("description", "")
    image_url   = fetch_image(name, description)
    return jsonify({"image_url": image_url})


@api_bp.route("/api/fetch-images")
@login_required
def api_fetch_images():
    """
    Fetch multiple product image URLs.
    ---
    tags:
      - Images API
    summary: Auto-fetch up to 6 images for a product
    description: |
      Runs the same cascade as /api/fetch-image but returns up to 6 results.
      Used by the admin image-picker. Requires admin session.
    parameters:
      - name: name
        in: query
        type: string
        required: true
        description: Product name used as search query
      - name: description
        in: query
        type: string
        required: false
        description: Product description for additional search context
    responses:
      200:
        description: Array of image URLs (always exactly 6 entries)
        schema:
          type: object
          properties:
            images:
              type: array
              items:
                type: string
              example:
                - "https://images.unsplash.com/photo-abc?w=640"
                - "https://images.unsplash.com/photo-def?w=640"
      302:
        description: Redirect to /admin/login if not authenticated
    """
    name        = request.args.get("name", "")
    description = request.args.get("description", "")
    images      = fetch_images(name, description, count=6)
    return jsonify({"images": images})


@api_bp.route("/api/categories", methods=["GET"])
@login_required
def api_get_categories():
    """
    List all categories.
    ---
    tags:
      - Categories API
    summary: Get all categories sorted by name
    description: Requires admin session.
    responses:
      200:
        description: Array of category objects sorted alphabetically
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: string
                description: MongoDB ObjectId string
                example: "6630f1a2b4e1c200123abcde"
              name:
                type: string
                example: "Cables"
      302:
        description: Redirect to /admin/login if not authenticated
    """
    return jsonify(get_all_categories_with_ids())


@api_bp.route("/api/categories", methods=["POST"])
@login_required
def api_create_category():
    """
    Create or find a category.
    ---
    tags:
      - Categories API
    summary: Case-insensitive find-or-create a category
    description: |
      If a category with the same name already exists (case-insensitive), it is
      returned unchanged. Otherwise a new category is created. Requires admin session.
    consumes:
      - application/json
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - name
          properties:
            name:
              type: string
              example: "Keyboards"
    responses:
      201:
        description: Category created or found
        schema:
          type: object
          properties:
            id:
              type: string
              example: "6630f1a2b4e1c200123abcde"
            name:
              type: string
              example: "Keyboards"
      400:
        description: Missing or empty name field
        schema:
          type: object
          properties:
            error:
              type: string
              example: "name is required"
      302:
        description: Redirect to /admin/login if not authenticated
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
    User registration.
    ---
    tags:
      - User Auth
    summary: Create a new user account
    description: |
      GET returns the registration form. POST creates the account with a
      bcrypt-hashed password and sends a verification email.
      The account cannot be used until the email link is clicked.
    parameters:
      - name: email
        in: formData
        type: string
        required: false
        description: User email address (POST only)
      - name: password
        in: formData
        type: string
        required: false
        description: Password (min 6 characters, POST only)
      - name: confirm_password
        in: formData
        type: string
        required: false
        description: Must match password (POST only)
    responses:
      200:
        description: Registration form (GET), or form with validation error (POST)
      302:
        description: Redirect to verification-sent page on success
    """
    error = None

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not email or not password:
            error = "Email and password are required."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif get_user_by_email(email):
            error = "An account with this email already exists."
        else:
            from app import bcrypt
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            user_id = create_user(email, password_hash)

            user = get_user_by_email(email)
            send_verification_email(email, user["verification_token"])

            return render_template("verification_sent.html", email=email)

    return render_template("user_register.html", error=error)


@user_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """
    User login.
    ---
    tags:
      - User Auth
    summary: Authenticate a user and create a session
    description: |
      GET returns the login form. POST validates credentials and starts a session
      with a 30-minute inactivity timeout.
      **Rate limited:** 10 requests/minute per IP.
      Supports a `?next=` query parameter for post-login redirect (relative paths only).
    parameters:
      - name: next
        in: query
        type: string
        required: false
        description: Relative URL to redirect to after successful login
      - name: email
        in: formData
        type: string
        required: false
        description: User email address (POST only)
      - name: password
        in: formData
        type: string
        required: false
        description: User password (POST only)
    responses:
      200:
        description: Login form (GET), or form with error message (POST on failure)
      302:
        description: Redirect to home (or ?next= path) on successful login
      429:
        description: Too many requests — rate limit exceeded
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
            from app import bcrypt
            if bcrypt.check_password_hash(user["password_hash"], password):
                session["user_id"] = user["_id"]
                session["user_last_seen"] = datetime.now(timezone.utc).isoformat()
                next_url = request.args.get("next", "")
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("public.index"))
            else:
                error = "Invalid email or password."

    return render_template("user_login.html", error=error)


@user_bp.route("/logout")
def logout():
    """
    User logout.
    ---
    tags:
      - User Auth
    summary: Destroy user session and clear cart
    responses:
      302:
        description: Redirect to storefront
    """
    session.pop("user_id", None)
    session.pop("cart", None)
    session.pop("user_last_seen", None)
    return redirect(url_for("public.index"))


@user_bp.route("/verify-email/<token>")
def verify_email(token):
    """
    Email verification.
    ---
    tags:
      - User Auth
    summary: Verify a user's email address via token link
    description: |
      Tokens are generated at registration and expire after 24 hours.
      After verification the user can log in normally.
    parameters:
      - name: token
        in: path
        type: string
        required: true
        description: URL-safe verification token from the registration email
    responses:
      200:
        description: HTML result page (success or expired/invalid token)
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
    """
    View shopping cart.
    ---
    tags:
      - Cart
    summary: Display the current session cart
    description: Cart is stored in the Flask session (not in the database).
    responses:
      200:
        description: HTML cart page with items, quantities, and totals
    """
    cart = get_cart()

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
    """
    Add item to cart.
    ---
    tags:
      - Cart
    summary: Add a product to the session cart (JSON response)
    description: |
      Validates stock before adding. If the item is already in the cart with the
      same color, the quantity is incremented. Returns JSON.
    parameters:
      - name: item_id
        in: formData
        type: string
        required: true
        description: MongoDB ObjectId of the product
      - name: quantity
        in: formData
        type: integer
        required: false
        default: 1
        description: Number of units to add
      - name: selected_color
        in: formData
        type: string
        required: false
        description: Color variant name (required when product has colors_enabled=true)
    responses:
      200:
        description: Item added or quantity updated
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            item_count:
              type: integer
              description: Total number of items in cart after the operation
              example: 3
            message:
              type: string
              example: "Added to cart"
      400:
        description: Item not found, out of stock, or insufficient stock
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Only 2 in stock"
    """
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
    """
    Remove item from cart.
    ---
    tags:
      - Cart
    summary: Remove a product from the session cart
    description: Redirects back to the cart page after removal.
    parameters:
      - name: item_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the product to remove
      - name: selected_color
        in: formData
        type: string
        required: false
        description: Color variant to remove (must match the cart entry)
    responses:
      302:
        description: Redirect to /cart
    """
    selected_color = request.form.get("selected_color")
    remove_from_cart(item_id, selected_color)
    return redirect(url_for("user.view_cart"))


@user_bp.route("/cart/update", methods=["POST"])
def update_cart_route():
    """
    Update cart item quantity.
    ---
    tags:
      - Cart
    summary: Change the quantity of a cart item
    description: |
      If `X-Requested-With: XMLHttpRequest` is present (or JSON is accepted), returns
      JSON with updated totals. Otherwise redirects to /cart.
      Setting quantity to 0 removes the item.
    parameters:
      - name: item_id
        in: formData
        type: string
        required: true
        description: MongoDB ObjectId of the product
      - name: quantity
        in: formData
        type: integer
        required: true
        description: New quantity (0 to remove the item)
      - name: selected_color
        in: formData
        type: string
        required: false
        description: Color variant to update
    responses:
      200:
        description: Updated totals (AJAX / JSON response)
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            totals:
              type: object
              properties:
                subtotal:
                  type: number
                  example: 49.98
                shipping:
                  type: number
                  example: 5.99
                total:
                  type: number
                  example: 55.97
                item_count:
                  type: integer
                  example: 2
            message:
              type: string
              example: "Quantity updated"
      400:
        description: Insufficient stock or item not in cart (AJAX response)
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Only 1 in stock"
      302:
        description: Redirect to /cart (non-AJAX form submission)
    """
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
    Checkout.
    ---
    tags:
      - Checkout
    summary: Review cart and place an order
    description: |
      GET shows the checkout form with cart summary. POST creates the order,
      decrements inventory, sends a confirmation email, and clears the cart.
      Stock is validated before showing the form and again before order creation
      to prevent overselling. Requires user session.
    parameters:
      - name: name
        in: formData
        type: string
        required: false
        description: Recipient full name (POST only)
      - name: address
        in: formData
        type: string
        required: false
        description: Street address (POST only)
      - name: city
        in: formData
        type: string
        required: false
        description: City (POST only)
      - name: state
        in: formData
        type: string
        required: false
        description: State / province (POST only)
      - name: zip
        in: formData
        type: string
        required: false
        description: Postal code (POST only)
      - name: country
        in: formData
        type: string
        required: false
        default: USA
        description: Country (POST only)
    responses:
      200:
        description: HTML checkout form with cart summary (GET), or error message (POST on validation failure)
      302:
        description: |
          Redirect to /order/<order_id> on success (POST), or to /cart if cart is empty.
          Redirect to /login if not authenticated.
    """
    cart = get_cart()
    totals = get_cart_total()

    if not cart:
        return redirect(url_for("user.view_cart"))

    stock_validation = validate_cart_stock()
    if not stock_validation["valid"]:
        error_message = "Some items in your cart are no longer available or have insufficient stock:<br>"
        for issue in stock_validation["issues"]:
            error_message += f"• {html.escape(issue['name'])}: {html.escape(issue['issue'])}<br>"
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
    """
    Order confirmation.
    ---
    tags:
      - Checkout
    summary: Order placed successfully page
    description: |
      Shown after a successful checkout. Verifies the order belongs to the
      logged-in user before rendering. Requires user session.
    parameters:
      - name: order_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the order
    responses:
      200:
        description: HTML order confirmation page with order summary
      403:
        description: Order belongs to a different user
      404:
        description: Order not found
    """
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
    """
    User account dashboard.
    ---
    tags:
      - Account
    summary: Account overview with 5 most recent orders
    description: Requires user session (30-minute inactivity timeout).
    responses:
      200:
        description: HTML account page with user info and recent orders
      302:
        description: Redirect to /login if not authenticated or session expired
    """
    user = get_current_user()
    orders = get_user_orders(user["_id"])
    return render_template("user_account.html", user=user, orders=orders[:5])


@user_bp.route("/orders")
@user_login_required
def order_history():
    """
    Full order history.
    ---
    tags:
      - Account
    summary: Complete list of user orders (newest first)
    description: Requires user session.
    responses:
      200:
        description: HTML account page showing all orders
      302:
        description: Redirect to /login if not authenticated
    """
    user = get_current_user()
    orders = get_user_orders(user["_id"])
    return render_template("user_account.html", user=user, orders=orders)


@user_bp.route("/orders/<order_id>")
@user_login_required
def order_detail(order_id):
    """
    Order detail.
    ---
    tags:
      - Account
    summary: Full detail view of a single order
    description: |
      Verifies the order belongs to the logged-in user. Requires user session.
    parameters:
      - name: order_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the order
    responses:
      200:
        description: HTML order detail page
      403:
        description: Order belongs to a different user
      404:
        description: Order not found
    """
    order = get_order_by_id(order_id)
    if not order:
        return "Order not found", 404

    if order["user_id"] != session["user_id"]:
        return "Unauthorized", 403

    return render_template("order_detail.html", order=order)


# ── Admin User Management Routes ──────────────────────────────────────────────

@admin_bp.route("/admin/analytics")
@login_required
def admin_analytics():
    """
    Analytics dashboard.
    ---
    tags:
      - Admin – Analytics
    summary: Sales, popularity, and user metrics charts
    description: Requires admin session.
    responses:
      200:
        description: HTML analytics page with charts and aggregated data
      302:
        description: Redirect to /admin/login if not authenticated
    """
    return render_template("admin_analytics.html", data=dashboard_payload())


@admin_bp.route("/admin/users")
@login_required
def admin_users():
    """
    List all users.
    ---
    tags:
      - Admin – Users
    summary: User table with order count and spend statistics
    description: Requires admin session.
    responses:
      200:
        description: HTML user list with stats
      302:
        description: Redirect to /admin/login if not authenticated
    """
    users = get_all_users_with_stats()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/admin/users/<user_id>")
@login_required
def admin_user_detail(user_id):
    """
    User detail (admin).
    ---
    tags:
      - Admin – Users
    summary: Full profile and order history for one user
    description: Requires admin session.
    parameters:
      - name: user_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the user
    responses:
      200:
        description: HTML user detail page with all orders and total spend
      404:
        description: User not found
    """
    from user_models import get_user_by_id
    user = get_user_by_id(user_id)
    if not user:
        return "User not found", 404

    orders = get_user_orders(user_id)
    total_spent = sum(order.get("total", 0) for order in orders)

    return render_template("admin_user_detail.html", user=user, orders=orders, total_spent=total_spent)


@admin_bp.route("/admin/users/new", methods=["GET", "POST"])
@login_required
def admin_add_user():
    """
    Create a user (admin).
    ---
    tags:
      - Admin – Users
    summary: Manually create a user account
    description: |
      Admin can optionally mark the account as already verified, bypassing
      the email verification step. Requires admin session.
    parameters:
      - name: email
        in: formData
        type: string
        required: false
        description: User email address (POST only)
      - name: password
        in: formData
        type: string
        required: false
        description: Plain-text password — will be bcrypt-hashed before storing (POST only)
      - name: is_verified
        in: formData
        type: string
        required: false
        description: Set to "1" to mark account as email-verified immediately
    responses:
      200:
        description: HTML create-user form (GET), or form with error (POST on validation failure)
      302:
        description: Redirect to /admin/users on success
    """
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
            from app import bcrypt
            password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            user_id = create_user(email, password_hash)
            if is_verified:
                update_user(user_id, email, is_verified=True)
            return redirect(url_for("admin.admin_users"))

    return render_template("admin_user_form.html", action="Add", user=None, error=error)


@admin_bp.route("/admin/users/<user_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_user(user_id):
    """
    Edit a user (admin).
    ---
    tags:
      - Admin – Users
    summary: Update a user's email, password, or verification status
    description: |
      Leave password blank to keep the existing one. Requires admin session.
    parameters:
      - name: user_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the user
      - name: email
        in: formData
        type: string
        required: false
        description: New email address (POST only)
      - name: password
        in: formData
        type: string
        required: false
        description: New password — leave blank to keep current (POST only)
      - name: is_verified
        in: formData
        type: string
        required: false
        description: Set to "1" to mark account as verified (POST only)
    responses:
      200:
        description: HTML edit-user form pre-filled with current values (GET)
      302:
        description: Redirect to /admin/users on success
      404:
        description: User not found
    """
    from user_models import get_user_by_id
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
                from app import bcrypt
                password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            update_user(user_id, email, password_hash=password_hash, is_verified=is_verified)
            return redirect(url_for("admin.admin_users"))

    return render_template("admin_user_form.html", action="Edit", user=user, error=error)


@admin_bp.route("/admin/users/<user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    """
    Delete a user (admin).
    ---
    tags:
      - Admin – Users
    summary: Permanently delete a user account
    description: This action is irreversible. Requires admin session.
    parameters:
      - name: user_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the user to delete
    responses:
      302:
        description: Redirect to /admin/users
    """
    delete_user(user_id)
    return redirect(url_for("admin.admin_users"))


@admin_bp.route("/admin/orders")
@login_required
def admin_orders():
    """
    List all orders (admin).
    ---
    tags:
      - Admin – Orders
    summary: All orders across all users, newest first
    description: Requires admin session.
    responses:
      200:
        description: HTML order list with status, user, and totals
      302:
        description: Redirect to /admin/login if not authenticated
    """
    orders = get_all_orders()
    return render_template("admin_orders.html", orders=orders)


@admin_bp.route("/admin/orders/<order_id>/status", methods=["POST"])
@login_required
def admin_update_order_status(order_id):
    """
    Update order status (admin).
    ---
    tags:
      - Admin – Orders
    summary: Change an order's fulfillment status and notify the customer
    description: |
      Accepted status values: `pending`, `confirmed`, `shipped`, `delivered`.
      A status-update email is sent to the customer on success.
      Requires admin session.
    parameters:
      - name: order_id
        in: path
        type: string
        required: true
        description: MongoDB ObjectId of the order
      - name: status
        in: formData
        type: string
        required: true
        description: "New status: pending | confirmed | shipped | delivered"
    responses:
      302:
        description: Redirect to /admin/orders (invalid status values are silently ignored)
    """
    from user_models import update_order_status
    from email_service import send_order_status_update
    status = request.form.get("status", "").strip()
    if status in ("pending", "confirmed", "shipped", "delivered"):
        order = update_order_status(order_id, status)
        if order:
            try:
                send_order_status_update(order["user_email"], order)
            except Exception:
                pass
    return redirect(url_for("admin.admin_orders"))
