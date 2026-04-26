"""
models.py
─────────
Contains all data-layer logic:
  - Item CRUD operations (create, read, update, delete)
  - Image auto-fetch via Unsplash API
  - Demo data seeding
  - ObjectId serialization helper

No Flask imports here — this file is purely about data, not HTTP.
"""

import os
import requests
from bson import ObjectId
from datetime import datetime
from ddgs import DDGS

from database import items_collection  # import the shared collection


# ── Unsplash API key (optional — set UNSPLASH_ACCESS_KEY in your .env file) ────
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")


# ══════════════════════════════════════════════════════════════════════════════
#  SERIALIZATION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def serialize_item(item: dict) -> dict:
    """Convert MongoDB ObjectId to a plain string so it can be used in templates/JSON."""
    if item and "_id" in item:
        item["_id"] = str(item["_id"])  # ObjectId → string
    return item


# ══════════════════════════════════════════════════════════════════════════════
#  READ
# ══════════════════════════════════════════════════════════════════════════════

def get_all_items(category: str = "", search: str = "") -> list:
    """
    Fetch all items from MongoDB, with optional category filter and text search.
    Returns a list of plain dicts (ObjectIds already converted to strings).
    """
    query = {}

    if category:
        query["category"] = category  # exact match on category field

    if search:
        # Case-insensitive regex search across name and description
        query["$or"] = [
            {"name":        {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]

    items = list(items_collection.find(query))  # run the query
    return [serialize_item(item) for item in items]  # serialize every item


def get_item_by_id(item_id: str) -> dict | None:
    """
    Fetch a single item by its string ID.
    Returns None if the ID is invalid or the item doesn't exist.
    """
    try:
        item = items_collection.find_one({"_id": ObjectId(item_id)})  # convert str → ObjectId
        return serialize_item(item) if item else None
    except Exception:
        return None  # invalid ObjectId format


def get_all_categories() -> list:
    """Return a sorted list of unique category strings."""
    return sorted(items_collection.distinct("category"))


# ══════════════════════════════════════════════════════════════════════════════
#  CREATE
# ══════════════════════════════════════════════════════════════════════════════

def create_item(name: str, description: str, category: str,
                price: float, stock: int, image_url: str,
                colors_enabled: bool = False, colors: list = None) -> str:
    if not image_url:
        image_url = fetch_image(name, description)

    document = {
        "name":           name,
        "description":    description,
        "category":       category,
        "price":          float(price),
        "stock":          int(stock),
        "image_url":      image_url,
        "colors_enabled": colors_enabled,
        "colors":         colors or [],
        "created_at":     datetime.utcnow(),
    }

    result = items_collection.insert_one(document)
    return str(result.inserted_id)


# ══════════════════════════════════════════════════════════════════════════════
#  UPDATE
# ══════════════════════════════════════════════════════════════════════════════

def update_item(item_id: str, name: str, description: str, category: str,
                price: float, stock: int, image_url: str,
                colors_enabled: bool = False, colors: list = None) -> bool:
    if not image_url:
        image_url = fetch_image(name, description)

    updates = {
        "name":           name,
        "description":    description,
        "category":       category,
        "price":          float(price),
        "stock":          int(stock),
        "image_url":      image_url,
        "colors_enabled": colors_enabled,
        "colors":         colors or [],
        "updated_at":     datetime.utcnow(),
    }

    result = items_collection.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": updates}
    )
    return result.modified_count > 0


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE
# ══════════════════════════════════════════════════════════════════════════════

def delete_item(item_id: str) -> bool:
    """
    Delete an item by its string ID.
    Returns True if a document was deleted, False otherwise.
    """
    try:
        result = items_collection.delete_one({"_id": ObjectId(item_id)})
        return result.deleted_count > 0  # True if item was found and removed
    except Exception:
        return False  # invalid ID format or not found


# ══════════════════════════════════════════════════════════════════════════════
#  IMAGE FETCH
# ══════════════════════════════════════════════════════════════════════════════

def fetch_image(name: str, description: str) -> str:
    """
    Fetch a relevant product image URL for the given item name + description.

    Priority:
      1. Unsplash API  — if UNSPLASH_ACCESS_KEY is set in .env
      2. DuckDuckGo image search — free, no API key required
      3. picsum.photos placeholder — last resort fallback
    """
    query = f"{name} computer accessory product"

    # ── 1. Unsplash (optional, higher quality) ─────────────────────────────────
    if UNSPLASH_ACCESS_KEY and UNSPLASH_ACCESS_KEY != "your_unsplash_access_key_here":
        try:
            response = requests.get(
                "https://api.unsplash.com/search/photos",
                params={
                    "query":       query,
                    "per_page":    1,
                    "orientation": "landscape",
                    "client_id":   UNSPLASH_ACCESS_KEY,
                },
                timeout=5,
            )
            results = response.json().get("results", [])
            if results:
                return results[0]["urls"]["regular"]
        except Exception as e:
            print(f"[models] Unsplash fetch failed: {e}")

    # ── 2. DuckDuckGo image search (free, no API key) ──────────────────────────
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=5))
            for r in results:
                url = r.get("image", "")
                if url and url.startswith("http"):
                    return url
    except Exception as e:
        print(f"[models] DuckDuckGo image fetch failed: {e}")

    # ── 3. Fallback placeholder ────────────────────────────────────────────────
    seed = abs(hash(name)) % 1000
    return f"https://picsum.photos/seed/{seed}/640/400"


# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

def seed_demo_data():
    """
    Insert 8 sample items into MongoDB if the collection is empty.
    Called once when the app starts — safe to leave in production,
    it checks first before inserting anything.
    """
    if items_collection.count_documents({}) > 0:
        return  # collection already has data — do nothing

    demo_items = [
        {"name": "USB-C Hub 7-in-1",          "description": "Multiport adapter with HDMI, USB 3.0, SD card reader, PD charging",          "category": "Adapters",         "price": 39.99, "stock": 42},
        {"name": "DisplayPort to HDMI Cable",  "description": "4K 60Hz DP to HDMI cable, 6ft braided nylon",                                 "category": "Cables",           "price": 14.99, "stock": 88},
        {"name": "Wireless Mouse Pad XL",      "description": "Extra-large desk pad with Qi wireless charging zone",                         "category": "Desk Accessories", "price": 29.99, "stock": 35},
        {"name": "Laptop Stand Aluminum",      "description": "Adjustable height aluminum laptop riser, foldable and ergonomic",             "category": "Laptop Accessories","price": 49.99, "stock": 20},
        {"name": "Mini LED Desk Light",        "description": "USB-powered LED lamp with touch dimmer and color temperature control",        "category": "Gadgets",          "price": 22.99, "stock": 60},
        {"name": "Cable Management Kit",       "description": "Velcro ties, clips and sleeves for a clean desk setup",                       "category": "Cables",           "price":  9.99, "stock":150},
        {"name": "Mechanical Keyboard TKL",    "description": "Tenkeyless mechanical keyboard with blue switches and RGB backlight",          "category": "Input Devices",    "price": 79.99, "stock": 15},
        {"name": "Webcam 1080p HD",            "description": "Full HD webcam with built-in noise-cancelling microphone, plug and play",     "category": "Gadgets",          "price": 59.99, "stock": 28},
    ]

    for item in demo_items:
        item["image_url"]  = fetch_image(item["name"], item["description"])
        item["created_at"] = datetime.utcnow()

    items_collection.insert_many(demo_items)
    print("✅ [models] Demo data seeded into MongoDB.")
