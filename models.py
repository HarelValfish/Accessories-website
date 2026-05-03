"""
models.py
─────────
Contains all data-layer logic:
  - Item CRUD operations (create, read, update, delete)
  - Category CRUD with get-or-create
  - Image auto-fetch via Unsplash API
  - Demo data seeding
  - ObjectId serialization helper
"""

import os
import re
import requests
from bson import ObjectId
from datetime import datetime, timezone
from ddgs import DDGS

from database import items_collection, categories_collection


UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")


# ══════════════════════════════════════════════════════════════════════════════
#  SALE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_sale_info(item: dict) -> dict:
    """Compute effective sale state for an item based on current UTC time."""
    sale_type  = item.get("sale_type") or ""
    sale_value = item.get("sale_value") or 0
    sale_start = item.get("sale_start")
    sale_end   = item.get("sale_end")
    price      = float(item.get("price") or 0)

    empty = {"active": False, "scheduled": False, "pct_off": 0.0,
             "sale_price": price, "original_price": price}

    if not sale_type or float(sale_value) <= 0:
        return empty

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if sale_end and now >= sale_end:
        return empty

    pv = float(sale_value)
    if sale_type == "percentage":
        pct_off    = min(pv, 100.0)
        sale_price = round(price * (1.0 - pct_off / 100.0), 2)
    elif sale_type == "amount":
        sale_price = max(0.0, round(price - pv, 2))
        pct_off    = round((price - sale_price) / price * 100.0, 1) if price > 0 else 0.0
    elif sale_type == "target_price":
        sale_price = round(pv, 2)
        pct_off    = round((price - sale_price) / price * 100.0, 1) if price > 0 else 0.0
    else:
        return empty

    if sale_start and now < sale_start:
        return {"active": False, "scheduled": True, "pct_off": pct_off,
                "sale_price": sale_price, "original_price": price}

    return {"active": True, "scheduled": False, "pct_off": pct_off,
            "sale_price": sale_price, "original_price": price}


def set_item_sale(item_id: str, sale_type: str, sale_value: float,
                  sale_start: datetime = None, sale_end: datetime = None) -> bool:
    try:
        result = items_collection.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {
                "sale_type":  sale_type,
                "sale_value": float(sale_value),
                "sale_start": sale_start,
                "sale_end":   sale_end,
            }}
        )
        return result.modified_count > 0
    except Exception:
        return False


def clear_item_sale(item_id: str) -> bool:
    try:
        result = items_collection.update_one(
            {"_id": ObjectId(item_id)},
            {"$unset": {"sale_type": "", "sale_value": "", "sale_start": "", "sale_end": ""}}
        )
        return result.modified_count > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  SERIALIZATION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def serialize_item(item: dict) -> dict:
    """Convert ObjectId fields to strings and attach computed sale fields."""
    if item and "_id" in item:
        item["_id"] = str(item["_id"])
    if item and item.get("category_id"):
        item["category_id"] = str(item["category_id"])
    if item:
        sale_info = get_sale_info(item)
        item["sale_active"]    = sale_info["active"]
        item["sale_scheduled"] = sale_info["scheduled"]
        item["sale_pct_off"]   = sale_info["pct_off"]
        item["sale_price"]     = sale_info["sale_price"]
    return item


# ══════════════════════════════════════════════════════════════════════════════
#  READ — ITEMS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_items(category: str = "", search: str = "") -> list:
    query = {}
    if category:
        query["category"] = category
    if search:
        query["$or"] = [
            {"name":        {"$regex": re.escape(search), "$options": "i"}},
            {"description": {"$regex": re.escape(search), "$options": "i"}},
        ]
    items = list(items_collection.find(query))
    return [serialize_item(item) for item in items]


def get_item_by_id(item_id: str) -> dict | None:
    try:
        item = items_collection.find_one({"_id": ObjectId(item_id)})
        return serialize_item(item) if item else None
    except Exception:
        return None


def get_all_categories() -> list:
    """Return sorted list of category name strings (for storefront filter pills)."""
    cats = list(categories_collection.find({}, {"name": 1}).sort("name", 1))
    if cats:
        return [c["name"] for c in cats]
    # Fallback for existing deployments without categories collection
    return sorted(items_collection.distinct("category"))


# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

def get_all_categories_with_ids() -> list:
    """Return all categories as [{id, name}] sorted by name."""
    cats = list(categories_collection.find({}, {"name": 1}).sort("name", 1))
    return [{"id": str(c["_id"]), "name": c["name"]} for c in cats]


def get_or_create_category(name: str) -> dict:
    """
    Case-insensitive find-or-create.
    Returns {"id": str, "name": str}.
    """
    name = name.strip()
    existing = categories_collection.find_one(
        {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    )
    if existing:
        return {"id": str(existing["_id"]), "name": existing["name"]}
    result = categories_collection.insert_one({"name": name})
    return {"id": str(result.inserted_id), "name": name}


def _resolve_category(category_id: str) -> tuple:
    """
    Look up a category by its string ID.
    Returns (ObjectId | None, name_str).
    """
    if not category_id:
        return None, ""
    try:
        oid = ObjectId(category_id)
        cat = categories_collection.find_one({"_id": oid})
        if cat:
            return oid, cat["name"]
    except Exception:
        pass
    return None, ""


# ══════════════════════════════════════════════════════════════════════════════
#  CREATE
# ══════════════════════════════════════════════════════════════════════════════

def create_item(name: str, description: str, category_id: str,
                price: float, stock: int, image_url: str,
                colors_enabled: bool = False, colors: list = None,
                images: list = None, cost: float = 0.0,
                sale_type: str = "", sale_value: float = 0.0,
                sale_start: datetime = None, sale_end: datetime = None) -> str:
    if not image_url:
        image_url = fetch_image(name, description)

    cat_oid, category_name = _resolve_category(category_id)

    document = {
        "name":           name,
        "description":    description,
        "category_id":    cat_oid,
        "category":       category_name,
        "price":          float(price),
        "cost":           float(cost),
        "stock":          int(stock),
        "image_url":      image_url,
        "images":         [u for u in (images or []) if u],
        "colors_enabled": colors_enabled,
        "colors":         colors or [],
        "sale_type":      sale_type or None,
        "sale_value":     float(sale_value) if sale_value else None,
        "sale_start":     sale_start,
        "sale_end":       sale_end,
        "created_at":     datetime.now(timezone.utc).replace(tzinfo=None),
    }

    result = items_collection.insert_one(document)
    return str(result.inserted_id)


# ══════════════════════════════════════════════════════════════════════════════
#  UPDATE
# ══════════════════════════════════════════════════════════════════════════════

def update_item(item_id: str, name: str, description: str, category_id: str,
                price: float, stock: int, image_url: str,
                colors_enabled: bool = False, colors: list = None,
                images: list = None, cost: float = 0.0,
                sale_type: str = "", sale_value: float = 0.0,
                sale_start: datetime = None, sale_end: datetime = None) -> bool:
    if not image_url:
        image_url = fetch_image(name, description)

    cat_oid, category_name = _resolve_category(category_id)

    updates = {
        "name":           name,
        "description":    description,
        "category_id":    cat_oid,
        "category":       category_name,
        "price":          float(price),
        "cost":           float(cost),
        "stock":          int(stock),
        "image_url":      image_url,
        "images":         [u for u in (images or []) if u],
        "colors_enabled": colors_enabled,
        "colors":         colors or [],
        "sale_type":      sale_type or None,
        "sale_value":     float(sale_value) if sale_value else None,
        "sale_start":     sale_start,
        "sale_end":       sale_end,
        "updated_at":     datetime.now(timezone.utc).replace(tzinfo=None),
    }

    result = items_collection.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": updates}
    )
    return result.modified_count > 0


# ══════════════════════════════════════════════════════════════════════════════
#  STOCK
# ══════════════════════════════════════════════════════════════════════════════

def decrement_stock(item_id: str, quantity: int) -> bool:
    """
    Atomically reduce an item's stock by quantity.
    The filter `stock >= quantity` ensures the update is skipped if stock
    was already exhausted between validation and order creation.
    Returns True if the decrement happened, False if stock was insufficient.
    """
    try:
        result = items_collection.update_one(
            {"_id": ObjectId(item_id), "stock": {"$gte": quantity}},
            {"$inc": {"stock": -quantity}},
        )
        return result.modified_count > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE
# ══════════════════════════════════════════════════════════════════════════════

def delete_item(item_id: str) -> bool:
    try:
        result = items_collection.delete_one({"_id": ObjectId(item_id)})
        return result.deleted_count > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  IMAGE FETCH
# ══════════════════════════════════════════════════════════════════════════════

def fetch_images(name: str, description: str, count: int = 3) -> list[str]:
    query = f"{name} computer accessory product"
    urls: list[str] = []

    if UNSPLASH_ACCESS_KEY and UNSPLASH_ACCESS_KEY != "your_unsplash_access_key_here":
        try:
            response = requests.get(
                "https://api.unsplash.com/search/photos",
                params={
                    "query":       query,
                    "per_page":    count,
                    "orientation": "landscape",
                    "client_id":   UNSPLASH_ACCESS_KEY,
                },
                timeout=5,
            )
            results = response.json().get("results", [])
            urls = [r["urls"]["regular"] for r in results[:count]]
        except Exception:
            pass

    if len(urls) < count:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=count * 2))
                for r in results:
                    url = r.get("image", "")
                    if url and url.startswith("http") and url not in urls:
                        urls.append(url)
                    if len(urls) >= count:
                        break
        except Exception:
            pass

    while len(urls) < count:
        seed = abs(hash(name + str(len(urls)))) % 1000
        urls.append(f"https://picsum.photos/seed/{seed}/640/400")

    return urls[:count]


def fetch_image(name: str, description: str) -> str:
    return fetch_images(name, description, count=1)[0]


# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

def seed_demo_data():
    if items_collection.count_documents({}) > 0:
        return

    demo_category_names = [
        "Adapters", "Cables", "Desk Accessories",
        "Laptop Accessories", "Gadgets", "Input Devices",
    ]
    cat_map = {name: get_or_create_category(name) for name in demo_category_names}

    demo_items = [
        {"name": "USB-C Hub 7-in-1",         "description": "Multiport adapter with HDMI, USB 3.0, SD card reader, PD charging",         "category": "Adapters",          "price": 39.99, "stock": 42},
        {"name": "DisplayPort to HDMI Cable", "description": "4K 60Hz DP to HDMI cable, 6ft braided nylon",                               "category": "Cables",            "price": 14.99, "stock": 88},
        {"name": "Wireless Mouse Pad XL",     "description": "Extra-large desk pad with Qi wireless charging zone",                       "category": "Desk Accessories",  "price": 29.99, "stock": 35},
        {"name": "Laptop Stand Aluminum",     "description": "Adjustable height aluminum laptop riser, foldable and ergonomic",           "category": "Laptop Accessories","price": 49.99, "stock": 20},
        {"name": "Mini LED Desk Light",       "description": "USB-powered LED lamp with touch dimmer and color temperature control",      "category": "Gadgets",           "price": 22.99, "stock": 60},
        {"name": "Cable Management Kit",      "description": "Velcro ties, clips and sleeves for a clean desk setup",                     "category": "Cables",            "price":  9.99, "stock":150},
        {"name": "Mechanical Keyboard TKL",   "description": "Tenkeyless mechanical keyboard with blue switches and RGB backlight",        "category": "Input Devices",     "price": 79.99, "stock": 15},
        {"name": "Webcam 1080p HD",           "description": "Full HD webcam with built-in noise-cancelling microphone, plug and play",   "category": "Gadgets",           "price": 59.99, "stock": 28},
    ]

    for item in demo_items:
        cat = cat_map.get(item["category"], {})
        item["category_id"] = ObjectId(cat["id"]) if cat.get("id") else None
        item["image_url"]   = fetch_image(item["name"], item["description"])
        item["created_at"]  = datetime.now(timezone.utc).replace(tzinfo=None)

    items_collection.insert_many(demo_items)
    print("✅ [models] Demo data seeded into MongoDB.")
