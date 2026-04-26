"""
database.py
───────────
Handles the MongoDB connection.
Credentials are read from the .env file — never hardcoded here.
"""

import os
import sys
import certifi
from pymongo import MongoClient

# ── Read connection string from .env (loaded by main.py before this runs) ──────
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    sys.exit("ERROR: MONGO_URI is not set. Add it to your .env file.")

# ── Create a single shared MongoClient ─────────────────────────────────────────
# tlsCAFile=certifi.where() fixes the macOS SSL certificate verification issue
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())

# ── Select the database and collections ────────────────────────────────────────
db               = client["techden"]   # database name
items_collection = db["items"]         # product inventory
users_collection = db["users"]         # user accounts
orders_collection = db["orders"]       # order history

# ── Create indexes for performance and uniqueness ──────────────────────────────
users_collection.create_index("email", unique=True)  # ensure unique emails
orders_collection.create_index("user_id")            # fast user order lookup
orders_collection.create_index("order_number", unique=True)  # unique order numbers
