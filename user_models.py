"""
user_models.py
──────────────
User and order CRUD operations for MongoDB.
Handles user registration, authentication, and order management.
"""

from datetime import datetime, timezone
from bson import ObjectId

from database import users_collection, orders_collection
from user_auth import generate_verification_token


# ══════════════════════════════════════════════════════════════════════════════
#  USER CRUD
# ══════════════════════════════════════════════════════════════════════════════

def create_user(email: str, password_hash: str) -> str:
    """
    Create a new user with hashed password and verification token.
    Returns the user ID string.
    """
    token, expires_at = generate_verification_token()

    document = {
        "email": email.lower().strip(),  # normalize email
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "is_verified": False,            # require email verification
        "verification_token": token,
        "token_expires_at": expires_at,
    }

    result = users_collection.insert_one(document)
    return str(result.inserted_id)


def get_user_by_email(email: str) -> dict | None:
    """
    Fetch a user by email address.
    Returns None if not found.
    """
    if not email:
        return None

    user = users_collection.find_one({"email": email.lower().strip()})
    if user:
        user["_id"] = str(user["_id"])  # convert ObjectId to string
    return user


def get_user_by_id(user_id: str) -> dict | None:
    """
    Fetch a user by their ID.
    Returns None if not found.
    """
    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except Exception:
        return None


def verify_user_email(token: str) -> bool:
    """
    Mark a user's email as verified using their verification token.
    Returns True if successful, False otherwise.
    """
    from user_auth import verify_token  # avoid circular import

    user = verify_token(token)
    if not user:
        return False

    # Mark user as verified and clear the token
    result = users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "is_verified": True,
                "verification_token": None,
                "token_expires_at": None,
            }
        }
    )
    return result.modified_count > 0


def get_all_users_with_stats():
    """
    Get all users with their order statistics for admin panel.
    Returns list of users with: email, created_at, order_count, total_spent, last_order_date.
    """
    users = list(users_collection.find())
    user_stats = []

    for user in users:
        user_id = user["_id"]

        # Get all orders for this user
        user_orders = list(orders_collection.find({"user_id": user_id}))

        # Calculate stats
        order_count = len(user_orders)
        total_spent = sum(order.get("total", 0) for order in user_orders)
        last_order_date = max(
            (order.get("created_at") for order in user_orders),
            default=None
        )

        user_stats.append({
            "_id": str(user_id),
            "email": user.get("email"),
            "created_at": user.get("created_at"),
            "is_verified": user.get("is_verified", False),
            "order_count": order_count,
            "total_spent": total_spent,
            "last_order_date": last_order_date,
        })

    return user_stats


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER CRUD
# ══════════════════════════════════════════════════════════════════════════════

def create_order(user_id: str, cart_items: list, shipping_address: dict, order_number: str) -> str:
    """
    Create a new order from cart items.
    Cart items should be list of dicts with: item_id, name, price, quantity, image_url, selected_color.
    Returns the order ID string.
    """
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")

    # Calculate totals
    subtotal = sum(item["price"] * item["quantity"] for item in cart_items)
    shipping = 5.99 if subtotal < 50 else 0  # free shipping over $50
    total = subtotal + shipping

    document = {
        "order_number": order_number,
        "user_id": ObjectId(user_id),
        "user_email": user["email"],
        "items": cart_items,  # snapshot of items at purchase time
        "subtotal": subtotal,
        "shipping": shipping,
        "total": total,
        "status": "pending",  # pending, confirmed, shipped, delivered
        "shipping_address": shipping_address,
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }

    result = orders_collection.insert_one(document)
    return str(result.inserted_id)


def get_order_by_id(order_id: str) -> dict | None:
    """
    Fetch a single order by ID.
    Returns None if not found.
    """
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
        if order:
            order["_id"] = str(order["_id"])
            order["user_id"] = str(order["user_id"])
        return order
    except Exception:
        return None


def get_user_orders(user_id: str) -> list:
    """
    Get all orders for a specific user, sorted by date (newest first).
    Returns list of order documents.
    """
    try:
        orders = list(orders_collection.find({"user_id": ObjectId(user_id)}).sort("created_at", -1))
        for order in orders:
            order["_id"] = str(order["_id"])
            order["user_id"] = str(order["user_id"])
        return orders
    except Exception:
        return []


def get_all_orders() -> list:
    """
    Get all orders across all users for admin view.
    Returns list sorted by date (newest first).
    """
    orders = list(orders_collection.find().sort("created_at", -1))
    for order in orders:
        order["_id"] = str(order["_id"])
        order["user_id"] = str(order["user_id"])
    return orders


def update_order_status(order_id: str, status: str) -> bool:
    """Update order status and return the updated order dict, or None on failure."""
    try:
        result = orders_collection.find_one_and_update(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)}},
            return_document=True,
        )
        if result:
            result["_id"] = str(result["_id"])
            result["user_id"] = str(result["user_id"])
        return result
    except Exception:
        return None


def update_user(user_id: str, email: str, password_hash: str = None, is_verified: bool = None) -> bool:
    updates = {"email": email.lower().strip(), "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)}
    if password_hash is not None:
        updates["password_hash"] = password_hash
    if is_verified is not None:
        updates["is_verified"] = is_verified
    try:
        result = users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updates}
        )
        return result.modified_count > 0
    except Exception:
        return False


def delete_user(user_id: str) -> bool:
    try:
        result = users_collection.delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0
    except Exception:
        return False


