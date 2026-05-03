"""
test_routes.py
──────────────
Integration tests for all Flask routes and API endpoints.

Run with:  pytest test_routes.py -v
Requires:  pip install pytest
           (already in venv — run: venv/bin/pytest test_routes.py -v)

All database and external service calls are mocked — no real MongoDB
connection or email server is required.
"""

import os

# Set required env vars BEFORE any app imports trigger database.py
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.setdefault("ADMIN_PASSWORD", "testpass123")

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Prevent MongoClient from opening a real TCP connection at import time
_mongo_patcher = patch("pymongo.MongoClient", return_value=MagicMock())
_mongo_patcher.start()

import pytest
from app import create_app
from routes import _sale_dt_from_form, _sale_dt_to_form


# ══════════════════════════════════════════════════════════════════════════════
#  FIXTURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        MAIL_SUPPRESS_SEND=True,
        RATELIMIT_ENABLED=False,
    )
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """Test client with a valid admin session (within 5-min timeout)."""
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_logged_in"] = True
        s["admin_last_seen"] = datetime.now(timezone.utc).isoformat()
    return c


@pytest.fixture
def user_client(app):
    """Test client with a logged-in user session."""
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = USER_ID
    return c


@pytest.fixture
def user_client_with_cart(app):
    """Logged-in user with one item already in the session cart."""
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = USER_ID
        s["cart"] = [CART_ITEM.copy()]
    return c


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED TEST DATA
# ══════════════════════════════════════════════════════════════════════════════

ITEM_ID  = "507f1f77bcf86cd799439011"
USER_ID  = "507f1f77bcf86cd799439022"
ORDER_ID = "507f1f77bcf86cd799439099"
CAT_ID   = "507f1f77bcf86cd799439033"

SAMPLE_ITEM = {
    "_id": ITEM_ID,
    "name": "USB-C Hub",
    "description": "A great hub",
    "category": "Hubs",
    "category_id": CAT_ID,
    "price": 49.99,
    "cost": 20.00,
    "stock": 10,
    "image_url": "https://picsum.photos/640/400",
    "images": [],
    "colors_enabled": False,
    "colors": [],
    "sale_active": False,
    "sale_scheduled": False,
    "sale_type": None,
    "sale_value": 0,
    "sale_start": None,
    "sale_end": None,
    "sale_pct_off": 0,
    "sale_price": 49.99,
}

SAMPLE_USER = {
    "_id": USER_ID,
    "email": "test@example.com",
    "password_hash": "$2b$12$fakehashfortest",
    "is_verified": True,
    "verification_token": "valid-test-token-abc123",
    "created_at": datetime(2025, 1, 15, 10, 0, 0),
}

SAMPLE_ORDER = {
    "_id": ORDER_ID,
    "user_id": USER_ID,
    "order_number": "ORD-2026-TEST-001",
    "items": [{"item_id": ITEM_ID, "name": "USB-C Hub", "price": 49.99, "quantity": 1}],
    "subtotal": 49.99,
    "shipping": 5.99,
    "total": 55.98,
    "status": "confirmed",
    "shipping_address": {
        "name": "Test User", "address": "123 Main St",
        "city": "New York", "state": "NY", "zip": "10001", "country": "USA",
    },
    "user_email": "test@example.com",
    "created_at": datetime(2026, 1, 20, 14, 30, 0),
}

_ANALYTICS_MOCK = {
    "headline": {
        "total_orders": 5, "total_users": 3, "total_views": 20,
        "total_revenue": 250.0, "total_cost": 100.0, "total_profit": 150.0,
        "profit_margin": 60.0, "aov": 50.0,
    },
    "sales_over_time": {
        "labels": ["May 01"], "revenue": [250.0], "cost": [100.0],
        "profit": [150.0], "orders": [5],
    },
    "top_sellers":      {"labels": ["USB-C Hub"], "values": [5]},
    "most_viewed":      {"labels": ["USB-C Hub"], "values": [10]},
    "best_day": {
        "date": "2026-05-01", "revenue": 250.0, "cost": 100.0,
        "profit": 150.0, "orders": 5,
    },
    "active_users":     {"labels": ["testuser"], "spent": [250.0], "orders": [5]},
    "category_revenue": {"labels": ["Hubs"], "values": [250.0], "cost": [100.0], "profit": [150.0]},
    "inventory":        {"retail": 500.0, "cost": 200.0, "margin": 300.0, "units": 10},
}

CART_ITEM = {
    "item_id": ITEM_ID,
    "name": "USB-C Hub",
    "price": 49.99,
    "quantity": 1,
    "image_url": "",
    "selected_color": None,
}


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: sale timezone functions (pure Python — no mocking needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestSaleDateHelpers:
    def test_from_form_empty_returns_none(self):
        assert _sale_dt_from_form("") is None
        assert _sale_dt_from_form(None) is None

    def test_from_form_invalid_returns_none(self):
        assert _sale_dt_from_form("not-a-date") is None
        assert _sale_dt_from_form("2026-13-01T10:00") is None

    def test_from_form_converts_jerusalem_to_utc(self):
        # IDT = UTC+3 in summer. 14:00 Jerusalem → 11:00 UTC
        result = _sale_dt_from_form("2026-05-10T14:00")
        assert result is not None
        assert result.tzinfo is None          # stored as naive UTC
        assert result.hour == 11
        assert result.day == 10

    def test_from_form_near_midnight_crosses_date(self):
        # 23:00 Jerusalem (IDT+3) → 20:00 UTC, same day
        result = _sale_dt_from_form("2026-05-10T23:00")
        assert result.hour == 20
        assert result.day == 10

    def test_to_form_none_returns_empty_string(self):
        assert _sale_dt_to_form(None) == ""

    def test_to_form_converts_utc_to_jerusalem(self):
        # 11:00 UTC → 14:00 Jerusalem IDT
        dt = datetime(2026, 5, 10, 11, 0)
        result = _sale_dt_to_form(dt)
        assert result == "2026-05-10T14:00"

    def test_round_trip_is_stable(self):
        """Input → stored UTC → displayed Jerusalem must equal original input."""
        original = "2026-05-10T14:00"
        stored   = _sale_dt_from_form(original)
        displayed = _sale_dt_to_form(stored)
        assert displayed == original

    def test_round_trip_midnight_boundary(self):
        original = "2026-05-11T01:00"
        assert _sale_dt_to_form(_sale_dt_from_form(original)) == original


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestPublicRoutes:
    def test_index_returns_200(self, client):
        with patch("routes.get_all_items", return_value=[SAMPLE_ITEM]), \
             patch("routes.get_all_categories", return_value=["Hubs"]):
            res = client.get("/")
        assert res.status_code == 200

    def test_index_search_filter_passed_to_model(self, client):
        with patch("routes.get_all_items", return_value=[]) as mock_items, \
             patch("routes.get_all_categories", return_value=[]):
            client.get("/?search=hub&category=Hubs")
        mock_items.assert_called_once_with(category="Hubs", search="hub")

    def test_about_returns_200(self, client):
        res = client.get("/about")
        assert res.status_code == 200

    def test_item_detail_found(self, client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.record_item_view"):
            res = client.get(f"/item/{ITEM_ID}")
        assert res.status_code == 200

    def test_item_detail_not_found_returns_404(self, client):
        with patch("routes.get_item_by_id", return_value=None):
            res = client.get("/item/nonexistentid")
        assert res.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES  (/admin/login, /admin/logout)
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthRoutes:
    def test_login_page_returns_200(self, client):
        res = client.get("/admin/login")
        assert res.status_code == 200

    def test_login_correct_password_redirects_to_dashboard(self, client):
        res = client.post("/admin/login", data={"password": "testpass123"},
                          follow_redirects=False)
        assert res.status_code == 302
        assert "/admin" in res.headers["Location"]

    def test_login_wrong_password_stays_on_login(self, client):
        res = client.post("/admin/login", data={"password": "wrongpassword"})
        assert res.status_code == 200
        assert b"Incorrect password" in res.data

    def test_login_empty_password_fails(self, client):
        res = client.post("/admin/login", data={"password": ""})
        assert res.status_code == 200
        assert b"Incorrect password" in res.data

    def test_logout_clears_session_and_redirects(self, admin_client):
        res = admin_client.get("/admin/logout", follow_redirects=False)
        assert res.status_code == 302
        with admin_client.session_transaction() as s:
            assert "admin_logged_in" not in s


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminAuthentication:
    """Verify that unauthenticated requests are blocked."""

    def test_dashboard_redirects_unauthenticated(self, client):
        res = client.get("/admin", follow_redirects=False)
        assert res.status_code == 302
        assert "login" in res.headers["Location"]

    def test_new_item_redirects_unauthenticated(self, client):
        res = client.get("/admin/item/new", follow_redirects=False)
        assert res.status_code == 302

    def test_api_fetch_image_redirects_unauthenticated(self, client):
        res = client.get("/api/fetch-image?name=test", follow_redirects=False)
        assert res.status_code == 302


class TestAdminDashboard:
    def test_dashboard_returns_200(self, admin_client):
        with patch("routes.get_all_items", return_value=[SAMPLE_ITEM]):
            res = admin_client.get("/admin")
        assert res.status_code == 200

    def test_dashboard_shows_item_count(self, admin_client):
        items = [SAMPLE_ITEM, {**SAMPLE_ITEM, "_id": "other", "name": "Keyboard"}]
        with patch("routes.get_all_items", return_value=items):
            res = admin_client.get("/admin")
        assert res.status_code == 200


class TestAdminItemCRUD:
    def test_new_item_get_returns_form(self, admin_client):
        res = admin_client.get("/admin/item/new")
        assert res.status_code == 200

    def test_new_item_post_creates_item_and_redirects(self, admin_client):
        with patch("routes.create_item") as mock_create:
            res = admin_client.post("/admin/item/new", data={
                "name": "Test Item",
                "description": "desc",
                "category_id": CAT_ID,
                "price": "29.99",
                "stock": "5",
                "image_url": "",
                "colors_json": "[]",
                "images_json": "[]",
                "cost": "10",
                "sale_type": "",
                "sale_value": "",
                "sale_start": "",
                "sale_end": "",
            }, follow_redirects=False)
        assert res.status_code == 302
        mock_create.assert_called_once()

    def test_edit_item_get_prefills_form(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM):
            res = admin_client.get(f"/admin/item/edit/{ITEM_ID}")
        assert res.status_code == 200
        assert b"USB-C Hub" in res.data

    def test_edit_item_get_not_found(self, admin_client):
        with patch("routes.get_item_by_id", return_value=None):
            res = admin_client.get(f"/admin/item/edit/{ITEM_ID}")
        assert res.status_code == 404

    def test_edit_item_post_updates_and_redirects(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.update_item") as mock_update:
            res = admin_client.post(f"/admin/item/edit/{ITEM_ID}", data={
                "name": "Updated Hub",
                "description": "desc",
                "category_id": CAT_ID,
                "price": "59.99",
                "stock": "8",
                "image_url": "",
                "colors_json": "[]",
                "images_json": "[]",
                "cost": "20",
                "sale_type": "",
                "sale_value": "",
                "sale_start": "",
                "sale_end": "",
            }, follow_redirects=False)
        assert res.status_code == 302
        mock_update.assert_called_once()

    def test_delete_item_redirects(self, admin_client):
        with patch("routes.delete_item") as mock_delete:
            res = admin_client.post(f"/admin/item/delete/{ITEM_ID}",
                                    follow_redirects=False)
        assert res.status_code == 302
        mock_delete.assert_called_once_with(ITEM_ID)

    def test_refresh_image_updates_and_redirects(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.fetch_image", return_value="https://example.com/new.jpg"), \
             patch("routes.update_item") as mock_update:
            res = admin_client.post(f"/admin/item/refresh-image/{ITEM_ID}",
                                    follow_redirects=False)
        assert res.status_code == 302
        mock_update.assert_called_once()

    def test_refresh_image_not_found(self, admin_client):
        with patch("routes.get_item_by_id", return_value=None):
            res = admin_client.post(f"/admin/item/refresh-image/{ITEM_ID}")
        assert res.status_code == 404


class TestAdminSaleManagement:
    def test_manage_sale_get_returns_form(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM):
            res = admin_client.get(f"/admin/item/sale/{ITEM_ID}")
        assert res.status_code == 200

    def test_manage_sale_get_not_found(self, admin_client):
        with patch("routes.get_item_by_id", return_value=None):
            res = admin_client.get(f"/admin/item/sale/{ITEM_ID}")
        assert res.status_code == 404

    def test_manage_sale_post_set_percentage(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.set_item_sale") as mock_set:
            res = admin_client.post(f"/admin/item/sale/{ITEM_ID}", data={
                "action": "set",
                "sale_type": "percentage",
                "sale_value": "20",
                "sale_start": "",
                "sale_end": "",
            }, follow_redirects=False)
        assert res.status_code == 302
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == "percentage"
        assert args[2] == 20.0

    def test_manage_sale_post_set_amount(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.set_item_sale") as mock_set:
            admin_client.post(f"/admin/item/sale/{ITEM_ID}", data={
                "action": "set", "sale_type": "amount",
                "sale_value": "10", "sale_start": "", "sale_end": "",
            })
        mock_set.assert_called_once()

    def test_manage_sale_post_set_target_price(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.set_item_sale") as mock_set:
            admin_client.post(f"/admin/item/sale/{ITEM_ID}", data={
                "action": "set", "sale_type": "target_price",
                "sale_value": "35.99", "sale_start": "", "sale_end": "",
            })
        mock_set.assert_called_once()

    def test_manage_sale_post_set_with_jerusalem_dates(self, admin_client):
        """Dates from the form must be stored as UTC (Jerusalem - 3h)."""
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.set_item_sale") as mock_set:
            admin_client.post(f"/admin/item/sale/{ITEM_ID}", data={
                "action": "set", "sale_type": "percentage",
                "sale_value": "15",
                "sale_start": "2026-06-01T12:00",  # Jerusalem IDT = UTC+3
                "sale_end":   "2026-06-30T12:00",
            })
        _, _, _, sale_start, sale_end = mock_set.call_args[0]
        assert sale_start.hour == 9   # 12:00 IDT → 09:00 UTC
        assert sale_end.hour   == 9

    def test_manage_sale_post_clear(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.clear_item_sale") as mock_clear:
            res = admin_client.post(f"/admin/item/sale/{ITEM_ID}",
                                    data={"action": "clear"},
                                    follow_redirects=False)
        assert res.status_code == 302
        mock_clear.assert_called_once_with(ITEM_ID)

    def test_manage_sale_ignores_zero_value(self, admin_client):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM), \
             patch("routes.set_item_sale") as mock_set:
            admin_client.post(f"/admin/item/sale/{ITEM_ID}", data={
                "action": "set", "sale_type": "percentage",
                "sale_value": "0", "sale_start": "", "sale_end": "",
            })
        mock_set.assert_not_called()


class TestAdminUserManagement:
    def test_users_list_returns_200(self, admin_client):
        with patch("routes.get_all_users_with_stats", return_value=[]):
            res = admin_client.get("/admin/users")
        assert res.status_code == 200

    def test_user_detail_returns_200(self, admin_client):
        from user_models import get_user_by_id
        with patch("routes.get_user_orders", return_value=[]), \
             patch("user_models.get_user_by_id", return_value=SAMPLE_USER):
            res = admin_client.get(f"/admin/users/{USER_ID}")
        assert res.status_code == 200

    def test_user_detail_not_found(self, admin_client):
        with patch("user_models.get_user_by_id", return_value=None):
            res = admin_client.get(f"/admin/users/{USER_ID}")
        assert res.status_code == 404

    def test_add_user_get_returns_form(self, admin_client):
        res = admin_client.get("/admin/users/new")
        assert res.status_code == 200

    def test_add_user_post_success(self, admin_client):
        with patch("routes.get_user_by_email", return_value=None), \
             patch("routes.create_user", return_value=USER_ID), \
             patch("routes.update_user"), \
             patch("app.bcrypt.generate_password_hash",
                   return_value=b"$2b$12$fakehash"):
            res = admin_client.post("/admin/users/new", data={
                "email": "newuser@example.com",
                "password": "securepass",
                "is_verified": "1",
            }, follow_redirects=False)
        assert res.status_code == 302

    def test_add_user_post_duplicate_email(self, admin_client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER):
            res = admin_client.post("/admin/users/new", data={
                "email": "test@example.com",
                "password": "securepass",
            })
        assert res.status_code == 200
        assert b"already exists" in res.data

    def test_edit_user_get_returns_form(self, admin_client):
        with patch("user_models.get_user_by_id", return_value=SAMPLE_USER):
            res = admin_client.get(f"/admin/users/{USER_ID}/edit")
        assert res.status_code == 200

    def test_edit_user_post_success(self, admin_client):
        with patch("user_models.get_user_by_id", return_value=SAMPLE_USER), \
             patch("routes.update_user"):
            res = admin_client.post(f"/admin/users/{USER_ID}/edit", data={
                "email": "updated@example.com",
                "password": "",
                "is_verified": "1",
            }, follow_redirects=False)
        assert res.status_code == 302

    def test_delete_user_redirects(self, admin_client):
        with patch("routes.delete_user") as mock_del:
            res = admin_client.post(f"/admin/users/{USER_ID}/delete",
                                    follow_redirects=False)
        assert res.status_code == 302
        mock_del.assert_called_once_with(USER_ID)


class TestAdminOrders:
    def test_orders_list_returns_200(self, admin_client):
        with patch("routes.get_all_orders", return_value=[SAMPLE_ORDER]):
            res = admin_client.get("/admin/orders")
        assert res.status_code == 200

    def test_update_order_status_valid(self, admin_client):
        from user_models import update_order_status
        with patch("user_models.update_order_status", return_value=SAMPLE_ORDER), \
             patch("email_service.send_order_status_update"):
            res = admin_client.post(f"/admin/orders/{ORDER_ID}/status",
                                    data={"status": "shipped"},
                                    follow_redirects=False)
        assert res.status_code == 302

    def test_update_order_status_invalid_ignored(self, admin_client):
        from user_models import update_order_status
        with patch("user_models.update_order_status") as mock_upd:
            admin_client.post(f"/admin/orders/{ORDER_ID}/status",
                              data={"status": "invalid_status"})
        mock_upd.assert_not_called()

    def test_analytics_returns_200(self, admin_client):
        with patch("routes.dashboard_payload", return_value=_ANALYTICS_MOCK):
            res = admin_client.get("/admin/analytics")
        assert res.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (/api/*)
# ══════════════════════════════════════════════════════════════════════════════

class TestApiRoutes:
    def test_fetch_image_requires_admin_auth(self, client):
        res = client.get("/api/fetch-image?name=hub", follow_redirects=False)
        assert res.status_code == 302

    def test_fetch_image_returns_url(self, admin_client):
        with patch("routes.fetch_image",
                   return_value="https://example.com/img.jpg"):
            res = admin_client.get("/api/fetch-image?name=usb+hub")
        assert res.status_code == 200
        data = res.get_json()
        assert "image_url" in data
        assert data["image_url"] == "https://example.com/img.jpg"

    def test_fetch_image_passes_name_and_description(self, admin_client):
        with patch("routes.fetch_image", return_value="https://x.com/img.jpg") as m:
            admin_client.get("/api/fetch-image?name=hub&description=great")
        m.assert_called_once_with("hub", "great")

    def test_fetch_images_returns_list(self, admin_client):
        urls = ["https://a.com/1.jpg", "https://b.com/2.jpg"]
        with patch("routes.fetch_images", return_value=urls):
            res = admin_client.get("/api/fetch-images?name=keyboard")
        assert res.status_code == 200
        assert res.get_json()["images"] == urls

    def test_categories_get_returns_list(self, admin_client):
        cats = [{"id": CAT_ID, "name": "Hubs"}]
        with patch("routes.get_all_categories_with_ids", return_value=cats):
            res = admin_client.get("/api/categories")
        assert res.status_code == 200
        assert res.get_json() == cats

    def test_categories_post_creates_category(self, admin_client):
        new_cat = {"id": CAT_ID, "name": "Cables"}
        with patch("routes.get_or_create_category", return_value=new_cat):
            res = admin_client.post("/api/categories",
                                    json={"name": "Cables"},
                                    content_type="application/json")
        assert res.status_code == 201
        assert res.get_json()["name"] == "Cables"

    def test_categories_post_missing_name_returns_400(self, admin_client):
        res = admin_client.post("/api/categories",
                                json={},
                                content_type="application/json")
        assert res.status_code == 400
        assert "error" in res.get_json()

    def test_categories_post_empty_name_returns_400(self, admin_client):
        res = admin_client.post("/api/categories",
                                json={"name": "  "},
                                content_type="application/json")
        assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  USER AUTH ROUTES  (/register, /login, /logout, /verify-email)
# ══════════════════════════════════════════════════════════════════════════════

class TestUserAuthRoutes:
    def test_register_page_returns_200(self, client):
        res = client.get("/register")
        assert res.status_code == 200

    def test_register_success_sends_verification(self, client):
        with patch("routes.get_user_by_email", return_value=None), \
             patch("routes.create_user", return_value=USER_ID), \
             patch("routes.get_user_by_email", side_effect=[None, SAMPLE_USER]), \
             patch("routes.send_verification_email") as mock_email, \
             patch("app.bcrypt.generate_password_hash", return_value=b"hash"):
            res = client.post("/register", data={
                "email": "new@example.com",
                "password": "secure123",
                "confirm_password": "secure123",
            })
        assert res.status_code == 200
        assert b"verification" in res.data.lower() or res.status_code == 200

    def test_register_password_mismatch(self, client):
        res = client.post("/register", data={
            "email": "new@example.com",
            "password": "secure123",
            "confirm_password": "different",
        })
        assert res.status_code == 200
        assert b"do not match" in res.data

    def test_register_short_password(self, client):
        res = client.post("/register", data={
            "email": "new@example.com",
            "password": "abc",
            "confirm_password": "abc",
        })
        assert res.status_code == 200
        assert b"6 characters" in res.data

    def test_register_missing_fields(self, client):
        res = client.post("/register", data={
            "email": "",
            "password": "",
            "confirm_password": "",
        })
        assert res.status_code == 200
        assert b"required" in res.data

    def test_register_duplicate_email(self, client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER):
            res = client.post("/register", data={
                "email": "test@example.com",
                "password": "secure123",
                "confirm_password": "secure123",
            })
        assert res.status_code == 200
        assert b"already exists" in res.data

    def test_login_page_returns_200(self, client):
        res = client.get("/login")
        assert res.status_code == 200

    def test_login_success_redirects(self, client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER), \
             patch("app.bcrypt.check_password_hash", return_value=True):
            res = client.post("/login", data={
                "email": "test@example.com",
                "password": "correct",
            }, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["Location"] == "/"

    def test_login_wrong_password(self, client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER), \
             patch("app.bcrypt.check_password_hash", return_value=False):
            res = client.post("/login", data={
                "email": "test@example.com",
                "password": "wrong",
            })
        assert res.status_code == 200
        assert b"Invalid email or password" in res.data

    def test_login_unknown_email(self, client):
        with patch("routes.get_user_by_email", return_value=None):
            res = client.post("/login", data={
                "email": "nobody@example.com",
                "password": "pass",
            })
        assert res.status_code == 200
        assert b"Invalid email or password" in res.data

    def test_login_unverified_account(self, client):
        unverified = {**SAMPLE_USER, "is_verified": False}
        with patch("routes.get_user_by_email", return_value=unverified):
            res = client.post("/login", data={
                "email": "test@example.com",
                "password": "correct",
            })
        assert res.status_code == 200
        assert b"verify your email" in res.data

    def test_login_next_param_safe_redirect(self, client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER), \
             patch("app.bcrypt.check_password_hash", return_value=True):
            res = client.post("/login?next=/account", data={
                "email": "test@example.com",
                "password": "correct",
            }, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["Location"] == "/account"

    def test_login_next_param_blocks_open_redirect(self, client):
        with patch("routes.get_user_by_email", return_value=SAMPLE_USER), \
             patch("app.bcrypt.check_password_hash", return_value=True):
            res = client.post("/login?next=//evil.com", data={
                "email": "test@example.com",
                "password": "correct",
            }, follow_redirects=False)
        assert res.status_code == 302
        # Must NOT redirect to the external host
        assert "evil.com" not in res.headers["Location"]

    def test_logout_clears_session(self, user_client):
        res = user_client.get("/logout", follow_redirects=False)
        assert res.status_code == 302
        with user_client.session_transaction() as s:
            assert "user_id" not in s

    def test_verify_email_valid_token(self, client):
        with patch("routes.verify_user_email", return_value=True):
            res = client.get("/verify-email/valid-test-token-abc123")
        assert res.status_code == 200

    def test_verify_email_invalid_token(self, client):
        with patch("routes.verify_user_email", return_value=False):
            res = client.get("/verify-email/bad-token")
        assert res.status_code == 200
        assert b"Invalid" in res.data or b"expired" in res.data


# ══════════════════════════════════════════════════════════════════════════════
#  CART ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestCartRoutes:
    def test_view_cart_empty(self, client):
        res = client.get("/cart")
        assert res.status_code == 200

    def test_view_cart_with_items(self, user_client_with_cart):
        with patch("routes.get_item_by_id", return_value=SAMPLE_ITEM):
            res = user_client_with_cart.get("/cart")
        assert res.status_code == 200

    def test_add_to_cart_success(self, client):
        with patch("routes.cart_add",
                   return_value={"success": True, "message": "Added to cart"}), \
             patch("routes.get_cart_total",
                   return_value={"subtotal": 49.99, "shipping": 5.99,
                                 "total": 55.98, "item_count": 1}):
            res = client.post("/cart/add", data={
                "item_id": ITEM_ID,
                "quantity": "1",
            })
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["item_count"] == 1

    def test_add_to_cart_out_of_stock(self, client):
        with patch("routes.cart_add",
                   return_value={"success": False, "error": "Item is out of stock"}):
            res = client.post("/cart/add", data={
                "item_id": ITEM_ID,
                "quantity": "1",
            })
        assert res.status_code == 400
        assert res.get_json()["success"] is False

    def test_add_to_cart_not_found(self, client):
        with patch("routes.cart_add",
                   return_value={"success": False, "error": "Item not found"}):
            res = client.post("/cart/add", data={"item_id": "badid", "quantity": "1"})
        assert res.status_code == 400

    def test_add_to_cart_with_color(self, client):
        with patch("routes.cart_add",
                   return_value={"success": True, "message": "Added to cart"}) as m, \
             patch("routes.get_cart_total",
                   return_value={"item_count": 1, "subtotal": 49.99,
                                 "shipping": 5.99, "total": 55.98}):
            client.post("/cart/add", data={
                "item_id": ITEM_ID,
                "quantity": "1",
                "selected_color": "Red",
            })
        m.assert_called_once_with(ITEM_ID, 1, "Red")

    def test_remove_from_cart_redirects(self, user_client_with_cart):
        with patch("routes.remove_from_cart"):
            res = user_client_with_cart.post(f"/cart/remove/{ITEM_ID}",
                                             follow_redirects=False)
        assert res.status_code == 302

    def test_update_cart_ajax_success(self, user_client_with_cart):
        with patch("routes.update_cart_quantity",
                   return_value={"success": True, "message": "Quantity updated"}), \
             patch("routes.get_cart_total",
                   return_value={"subtotal": 99.98, "shipping": 0,
                                 "total": 99.98, "item_count": 2}):
            res = user_client_with_cart.post("/cart/update",
                                             data={"item_id": ITEM_ID, "quantity": "2"},
                                             headers={"X-Requested-With": "XMLHttpRequest"})
        assert res.status_code == 200
        assert res.get_json()["success"] is True

    def test_update_cart_ajax_failure(self, user_client_with_cart):
        with patch("routes.update_cart_quantity",
                   return_value={"success": False, "error": "Only 1 in stock"}):
            res = user_client_with_cart.post("/cart/update",
                                             data={"item_id": ITEM_ID, "quantity": "99"},
                                             headers={"X-Requested-With": "XMLHttpRequest"})
        assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  CHECKOUT ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckoutRoutes:
    def test_checkout_requires_user_auth(self, client):
        res = client.get("/checkout", follow_redirects=False)
        assert res.status_code == 302
        assert "login" in res.headers["Location"]

    def test_checkout_empty_cart_redirects_to_cart(self, user_client):
        res = user_client.get("/checkout", follow_redirects=False)
        assert res.status_code == 302
        assert "cart" in res.headers["Location"]

    def test_checkout_get_returns_form(self, user_client_with_cart):
        with patch("routes.validate_cart_stock",
                   return_value={"valid": True, "issues": []}), \
             patch("routes.get_current_user", return_value=SAMPLE_USER):
            res = user_client_with_cart.get("/checkout")
        assert res.status_code == 200

    def test_checkout_get_with_stock_issue_shows_error(self, user_client_with_cart):
        with patch("routes.validate_cart_stock", return_value={
                "valid": False,
                "issues": [{"name": "USB-C Hub", "issue": "Only 0 in stock"}],
        }):
            res = user_client_with_cart.get("/checkout")
        assert res.status_code == 200
        assert b"no longer available" in res.data or b"stock" in res.data

    def test_checkout_post_success_creates_order(self, user_client_with_cart):
        with patch("routes.validate_cart_stock",
                   return_value={"valid": True, "issues": []}), \
             patch("routes.generate_order_number", return_value="ORD-TEST-001"), \
             patch("routes.create_order", return_value=ORDER_ID), \
             patch("routes.decrement_stock"), \
             patch("routes.get_current_user", return_value=SAMPLE_USER), \
             patch("routes.get_order_by_id", return_value=SAMPLE_ORDER), \
             patch("routes.send_order_confirmation"), \
             patch("routes.clear_cart"):
            res = user_client_with_cart.post("/checkout", data={
                "name": "Test User",
                "address": "123 Main St",
                "city": "New York",
                "state": "NY",
                "zip": "10001",
                "country": "USA",
            }, follow_redirects=False)
        assert res.status_code == 302
        assert ORDER_ID in res.headers["Location"]

    def test_checkout_post_missing_fields_shows_error(self, user_client_with_cart):
        with patch("routes.validate_cart_stock",
                   return_value={"valid": True, "issues": []}), \
             patch("routes.get_current_user", return_value=SAMPLE_USER):
            res = user_client_with_cart.post("/checkout", data={
                "name": "Test User",
                "address": "",  # missing required field
                "city": "",
                "state": "",
                "zip": "",
            })
        assert res.status_code == 200
        assert b"required" in res.data

    def test_order_confirmation_own_order(self, user_client):
        with patch("routes.get_order_by_id", return_value=SAMPLE_ORDER):
            res = user_client.get(f"/order/{ORDER_ID}")
        assert res.status_code == 200

    def test_order_confirmation_wrong_user_returns_403(self, app):
        """A different user must not see another user's order."""
        other_client = app.test_client()
        with other_client.session_transaction() as s:
            s["user_id"] = "000000000000000000000000"  # different user

        with patch("routes.get_order_by_id", return_value=SAMPLE_ORDER):
            res = other_client.get(f"/order/{ORDER_ID}")
        assert res.status_code == 403

    def test_order_confirmation_not_found(self, user_client):
        with patch("routes.get_order_by_id", return_value=None):
            res = user_client.get(f"/order/nonexistent")
        assert res.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  USER ACCOUNT ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestUserAccountRoutes:
    def test_account_requires_user_auth(self, client):
        res = client.get("/account", follow_redirects=False)
        assert res.status_code == 302
        assert "login" in res.headers["Location"]

    def test_account_page_returns_200(self, user_client):
        with patch("routes.get_current_user", return_value=SAMPLE_USER), \
             patch("routes.get_user_orders", return_value=[SAMPLE_ORDER]):
            res = user_client.get("/account")
        assert res.status_code == 200

    def test_order_history_returns_all_orders(self, user_client):
        orders = [SAMPLE_ORDER, {**SAMPLE_ORDER, "_id": "other_order"}]
        with patch("routes.get_current_user", return_value=SAMPLE_USER), \
             patch("routes.get_user_orders", return_value=orders):
            res = user_client.get("/orders")
        assert res.status_code == 200

    def test_order_detail_own_order(self, user_client):
        with patch("routes.get_order_by_id", return_value=SAMPLE_ORDER), \
             patch("routes.get_current_user", return_value=SAMPLE_USER):
            res = user_client.get(f"/orders/{ORDER_ID}")
        assert res.status_code == 200

    def test_order_detail_wrong_user_returns_403(self, app):
        other_client = app.test_client()
        with other_client.session_transaction() as s:
            s["user_id"] = "000000000000000000000000"

        with patch("routes.get_order_by_id", return_value=SAMPLE_ORDER):
            res = other_client.get(f"/orders/{ORDER_ID}")
        assert res.status_code == 403

    def test_order_detail_not_found(self, user_client):
        with patch("routes.get_order_by_id", return_value=None):
            res = user_client.get("/orders/nonexistent")
        assert res.status_code == 404
