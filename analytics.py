"""
analytics.py
────────────
Aggregates dashboard metrics from MongoDB:
  - Sales over time (daily revenue, last 30 days)
  - Item popularity (top sellers by units sold)
  - Item interest (view/click counts)
  - Most profitable day on record
  - Most active users
  - Category revenue breakdown
"""

from datetime import datetime, timedelta
from bson import ObjectId
from collections import defaultdict

from database import (
    orders_collection,
    users_collection,
    items_collection,
    views_collection,
)


def record_item_view(item_id: str, user_id: str | None = None) -> None:
    """Log a single product detail page view / interest click."""
    try:
        views_collection.insert_one({
            "item_id":   item_id,
            "user_id":   ObjectId(user_id) if user_id else None,
            "viewed_at": datetime.utcnow(),
        })
    except Exception:
        pass


def _item_cost_map() -> dict:
    """item_id (str) → current unit cost."""
    return {
        str(it["_id"]): float(it.get("cost", 0) or 0)
        for it in items_collection.find({}, {"cost": 1})
    }


def _order_cogs(order: dict, cost_map: dict) -> float:
    """Total cost of goods sold for a single order."""
    return sum(
        cost_map.get(line.get("item_id"), 0) * int(line.get("quantity", 0))
        for line in order.get("items", [])
    )


def sales_over_time(days: int = 30) -> dict:
    """Daily revenue, cost, profit, and order counts for the last `days` days."""
    cutoff = datetime.utcnow() - timedelta(days=days - 1)
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

    revenue = defaultdict(float)
    cost    = defaultdict(float)
    counts  = defaultdict(int)
    cost_map = _item_cost_map()

    for order in orders_collection.find({"created_at": {"$gte": cutoff}}):
        created = order.get("created_at")
        if not created:
            continue
        key = created.strftime("%Y-%m-%d")
        revenue[key] += float(order.get("total", 0))
        cost[key]    += _order_cogs(order, cost_map)
        counts[key]  += 1

    labels, rev, cst, prof, cnt = [], [], [], [], []
    for i in range(days):
        d = cutoff + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        labels.append(d.strftime("%b %d"))
        r = round(revenue[key], 2)
        c = round(cost[key], 2)
        rev.append(r)
        cst.append(c)
        prof.append(round(r - c, 2))
        cnt.append(counts[key])

    return {"labels": labels, "revenue": rev, "cost": cst, "profit": prof, "orders": cnt}


def top_selling_items(limit: int = 8) -> dict:
    """Total units sold per item — top N."""
    sold = defaultdict(int)
    names = {}

    for order in orders_collection.find():
        for it in order.get("items", []):
            iid = it.get("item_id")
            if not iid:
                continue
            sold[iid] += int(it.get("quantity", 0))
            names[iid] = it.get("name", "Unknown")

    ranked = sorted(sold.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "labels": [names.get(iid, "Unknown")[:24] for iid, _ in ranked],
        "values": [v for _, v in ranked],
    }


def most_viewed_items(limit: int = 8) -> dict:
    """Items with the most detail-page views (interest clicks)."""
    pipeline = [
        {"$group": {"_id": "$item_id", "views": {"$sum": 1}}},
        {"$sort": {"views": -1}},
        {"$limit": limit},
    ]
    rows = list(views_collection.aggregate(pipeline))

    labels, values = [], []
    for row in rows:
        try:
            item = items_collection.find_one({"_id": ObjectId(row["_id"])})
            name = item["name"] if item else "Deleted item"
        except Exception:
            name = "Unknown"
        labels.append(name[:24])
        values.append(row["views"])
    return {"labels": labels, "values": values}


def most_profitable_day() -> dict:
    """Single day with the highest *profit* (revenue − cost) ever recorded."""
    cost_map = _item_cost_map()
    daily = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "orders": 0})

    for order in orders_collection.find():
        created = order.get("created_at")
        if not created:
            continue
        key = created.strftime("%Y-%m-%d")
        daily[key]["revenue"] += float(order.get("total", 0))
        daily[key]["cost"]    += _order_cogs(order, cost_map)
        daily[key]["orders"]  += 1

    if not daily:
        return {"date": None, "revenue": 0, "cost": 0, "profit": 0, "orders": 0}

    best_key, best = max(
        daily.items(),
        key=lambda kv: kv[1]["revenue"] - kv[1]["cost"]
    )
    return {
        "date":    best_key,
        "revenue": round(best["revenue"], 2),
        "cost":    round(best["cost"], 2),
        "profit":  round(best["revenue"] - best["cost"], 2),
        "orders":  best["orders"],
    }


def most_active_users(limit: int = 6) -> dict:
    """Users ranked by total amount spent."""
    pipeline = [
        {"$group": {
            "_id": "$user_id",
            "spent":  {"$sum": "$total"},
            "orders": {"$sum": 1},
        }},
        {"$sort": {"spent": -1}},
        {"$limit": limit},
    ]
    rows = list(orders_collection.aggregate(pipeline))

    labels, spent, orders = [], [], []
    for row in rows:
        try:
            user = users_collection.find_one({"_id": row["_id"]})
            email = user["email"] if user else "deleted"
        except Exception:
            email = "unknown"
        # Anonymize a bit — show local part only
        labels.append(email.split("@")[0][:18])
        spent.append(round(row["spent"], 2))
        orders.append(row["orders"])
    return {"labels": labels, "spent": spent, "orders": orders}


def revenue_by_category() -> dict:
    """Revenue, cost, and profit broken down per item category."""
    cat_rev    = defaultdict(float)
    cat_cost   = defaultdict(float)

    item_cat = {}
    item_cost = {}
    for it in items_collection.find({}, {"category": 1, "cost": 1}):
        item_cat[str(it["_id"])]  = it.get("category", "Uncategorized")
        item_cost[str(it["_id"])] = float(it.get("cost", 0) or 0)

    for order in orders_collection.find():
        for line in order.get("items", []):
            iid = line.get("item_id")
            if not iid:
                continue
            cat = item_cat.get(iid, "Uncategorized")
            qty   = int(line.get("quantity", 0))
            price = float(line.get("price", 0))
            cat_rev[cat]  += price * qty
            cat_cost[cat] += item_cost.get(iid, 0) * qty

    sorted_cats = sorted(cat_rev.items(), key=lambda x: x[1], reverse=True)
    labels  = [c for c, _ in sorted_cats]
    revenue = [round(cat_rev[c], 2)  for c in labels]
    cost    = [round(cat_cost[c], 2) for c in labels]
    profit  = [round(r - c, 2) for r, c in zip(revenue, cost)]
    return {"labels": labels, "values": revenue, "cost": cost, "profit": profit}


def headline_stats() -> dict:
    """Top-line numbers shown above the charts."""
    total_orders  = orders_collection.count_documents({})
    total_users   = users_collection.count_documents({})
    total_views   = views_collection.count_documents({})

    cost_map = _item_cost_map()
    total_revenue = 0.0
    total_cost    = 0.0
    for order in orders_collection.find():
        total_revenue += float(order.get("total", 0))
        total_cost    += _order_cogs(order, cost_map)

    total_profit = total_revenue - total_cost
    margin = (total_profit / total_revenue * 100) if total_revenue else 0.0
    aov = total_revenue / total_orders if total_orders else 0.0

    return {
        "total_orders":  total_orders,
        "total_users":   total_users,
        "total_views":   total_views,
        "total_revenue": round(total_revenue, 2),
        "total_cost":    round(total_cost, 2),
        "total_profit":  round(total_profit, 2),
        "profit_margin": round(margin, 1),
        "aov":           round(aov, 2),
    }


def inventory_value() -> dict:
    """Current stock value at retail price and at cost."""
    retail_total = 0.0
    cost_total   = 0.0
    total_units  = 0
    for item in items_collection.find({}, {"price": 1, "cost": 1, "stock": 1}):
        stock  = int(item.get("stock", 0) or 0)
        price  = float(item.get("price", 0) or 0)
        cost   = float(item.get("cost", 0) or 0)
        retail_total += price * stock
        cost_total   += cost  * stock
        total_units  += stock
    return {
        "retail": round(retail_total, 2),
        "cost":   round(cost_total, 2),
        "margin": round(retail_total - cost_total, 2),
        "units":  total_units,
    }


def dashboard_payload() -> dict:
    """One call to assemble everything the analytics page needs."""
    return {
        "headline":         headline_stats(),
        "sales_over_time":  sales_over_time(30),
        "top_sellers":      top_selling_items(8),
        "most_viewed":      most_viewed_items(8),
        "best_day":         most_profitable_day(),
        "active_users":     most_active_users(6),
        "category_revenue": revenue_by_category(),
        "inventory":        inventory_value(),
    }
