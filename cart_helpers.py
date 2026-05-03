"""
cart_helpers.py
───────────────
Shopping cart session management utilities.
Cart is stored in Flask session for simplicity and performance.
"""

from flask import session
from models import get_item_by_id


# ══════════════════════════════════════════════════════════════════════════════
#  CART SESSION MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def get_cart() -> list:
    """
    Get the current cart from session.
    Returns list of cart items or empty list if cart doesn't exist.
    """
    return session.get("cart", [])


def add_to_cart(item_id: str, quantity: int = 1, selected_color: str = None) -> dict:
    """
    Add an item to the cart or update quantity if it already exists.
    Returns dict with success status and optional error message.
    """
    # Normalize empty string to None
    if selected_color == "":
        selected_color = None

    # Fetch item details from database
    item = get_item_by_id(item_id)
    if not item:
        return {"success": False, "error": "Item not found"}

    # Check stock availability
    available_stock = item.get("stock", 0)
    if available_stock <= 0:
        return {"success": False, "error": "Item is out of stock"}

    # Initialize cart if it doesn't exist
    if "cart" not in session:
        session["cart"] = []

    cart = session["cart"]

    # Check if item already in cart (same item_id and color)
    for cart_item in cart:
        cart_color = cart_item.get("selected_color")
        if cart_color == "":
            cart_color = None
        if cart_item["item_id"] == item_id and cart_color == selected_color:
            new_quantity = cart_item["quantity"] + quantity
            if new_quantity > available_stock:
                return {"success": False, "error": f"Only {available_stock} in stock"}
            cart_item["quantity"] = new_quantity
            # Refresh price in case sale started/ended since item was last added
            effective_price = item.get("sale_price", item["price"]) if item.get("sale_active") else item["price"]
            cart_item["price"] = effective_price
            session.modified = True
            return {"success": True, "message": "Quantity updated"}

    # Check if requested quantity exceeds stock for new item
    if quantity > available_stock:
        return {"success": False, "error": f"Only {available_stock} in stock"}

    # Add new item to cart — use discounted price if sale is active
    effective_price = item.get("sale_price", item["price"]) if item.get("sale_active") else item["price"]
    cart_item = {
        "item_id": item_id,
        "name": item["name"],
        "price": effective_price,
        "quantity": quantity,
        "image_url": item.get("image_url", ""),
        "selected_color": selected_color,
    }
    cart.append(cart_item)
    session.modified = True
    return {"success": True, "message": "Added to cart"}


def remove_from_cart(item_id: str, selected_color: str = None) -> bool:
    """
    Remove an item from the cart.
    Returns True if item was removed, False if not found.
    """
    # Normalize empty string to None
    if selected_color == "":
        selected_color = None

    if "cart" not in session:
        return False

    cart = session["cart"]
    original_length = len(cart)

    # Remove items matching item_id and color
    session["cart"] = [
        item for item in cart
        if not (item["item_id"] == item_id and
                (item.get("selected_color") or None) == selected_color)
    ]

    session.modified = True
    return len(session["cart"]) < original_length


def update_cart_quantity(item_id: str, quantity: int, selected_color: str = None) -> dict:
    """
    Update the quantity of an item in the cart.
    If quantity is 0 or negative, removes the item.
    Returns dict with success status and optional error message.
    """
    # Normalize empty string to None
    if selected_color == "":
        selected_color = None

    if "cart" not in session:
        return {"success": False, "error": "Cart is empty"}

    if quantity <= 0:
        remove_from_cart(item_id, selected_color)
        return {"success": True, "message": "Item removed"}

    # Check stock availability
    item = get_item_by_id(item_id)
    if not item:
        return {"success": False, "error": "Item not found"}

    available_stock = item.get("stock", 0)
    if quantity > available_stock:
        return {"success": False, "error": f"Only {available_stock} in stock"}

    cart = session["cart"]

    # Find and update the item
    for cart_item in cart:
        cart_color = cart_item.get("selected_color")
        if cart_color == "":
            cart_color = None
        if cart_item["item_id"] == item_id and cart_color == selected_color:
            cart_item["quantity"] = quantity
            session.modified = True
            return {"success": True, "message": "Quantity updated"}

    return {"success": False, "error": "Item not found in cart"}


def get_cart_total() -> dict:
    """
    Calculate cart totals.
    Returns dict with: subtotal, shipping, total, item_count.
    """
    cart = get_cart()

    subtotal = sum(item["price"] * item["quantity"] for item in cart)
    item_count = sum(item["quantity"] for item in cart)
    shipping = 5.99 if subtotal > 0 and subtotal < 50 else 0  # free shipping over $50
    total = subtotal + shipping

    return {
        "subtotal": subtotal,
        "shipping": shipping,
        "total": total,
        "item_count": item_count,
    }


def validate_cart_stock() -> dict:
    """
    Validate that all items in cart have sufficient stock.
    Returns dict with success status and list of items with insufficient stock.
    """
    cart = get_cart()
    issues = []

    for cart_item in cart:
        item = get_item_by_id(cart_item["item_id"])
        if not item:
            issues.append({
                "name": cart_item["name"],
                "issue": "Item no longer available"
            })
            continue

        available_stock = item.get("stock", 0)
        if cart_item["quantity"] > available_stock:
            issues.append({
                "name": cart_item["name"],
                "requested": cart_item["quantity"],
                "available": available_stock,
                "issue": f"Only {available_stock} in stock (you have {cart_item['quantity']} in cart)"
            })

    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


def clear_cart():
    """
    Clear all items from the cart.
    """
    session["cart"] = []
    session.modified = True
