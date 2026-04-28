# TechDen — Computer Accessories Store

A full-stack Flask e-commerce app for selling computer accessories, backed by MongoDB Atlas. Includes a customer-facing storefront, user accounts, a shopping cart, order management, and a password-protected admin panel with analytics.

---

## Features

- **Storefront** — Product grid with images, prices, stock status, category filters, and search
- **Item detail page** — Full product info, color variant selection, stock level, view tracking
- **User accounts** — Registration with email verification, login, order history, account management
- **Shopping cart** — Session-based cart with quantity controls and stock validation
- **Checkout & orders** — Shipping address collection, atomic stock decrement, email confirmation, unique order numbers (`ORD-YYYYMMDD-XXXX`)
- **Admin panel** — Password-protected dashboard: full product/category/user/order CRUD, low-stock warnings
- **Analytics dashboard** — Daily revenue (last 30 days), top sellers, item views, most profitable day, active users, category revenue breakdown
- **Auto image fetch** — Pulls product images from Unsplash API; falls back to DuckDuckGo image search, then placeholder images
- **MongoDB** — All data stored in the `techden` database with indexed collections

---

## Project Structure

```
├── main.py               # Entry point — loads .env, calls create_app(), seeds demo data
├── app.py                # App factory — registers extensions (bcrypt, CSRF, mail) and blueprints
├── routes.py             # All URL routes, organized into five blueprints
│
├── models.py             # Product & category CRUD, image fetch, demo seeding
├── user_models.py        # User & order CRUD
├── database.py           # Single shared MongoClient; exports all collections
│
├── auth.py               # Admin session auth (plain-text password vs ADMIN_PASSWORD env var)
├── user_auth.py          # User session auth — decorators, verification token generation
├── cart_helpers.py       # Cart stored in Flask session — add, remove, update, validate stock
│
├── analytics.py          # Aggregates dashboard metrics from MongoDB
├── email_service.py      # Flask-Mail — verification emails and order confirmations
├── order_generator.py    # Generates unique order numbers (ORD-YYYYMMDD-XXXX)
├── errors.py             # Global 404 / 500 error handlers
│
├── requirements.txt
├── templates/            # Jinja2 HTML templates
└── static/css/style.css  # Full stylesheet
```

### Blueprint layout (all routes in `routes.py`)

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `public_bp` | `/` | Storefront, item detail |
| `auth_bp` | `/admin/login`, `/admin/logout` | Admin session auth |
| `admin_bp` | `/admin/...` | Admin CRUD — items, users, orders, analytics |
| `api_bp` | `/api/...` | JSON endpoints (image fetch, categories) |
| `user_bp` | `/register`, `/login`, `/cart`, `/checkout`, `/account`, `/orders` | User accounts and shopping |

---

## Setup & Run

### 1. Install dependencies (use a virtualenv)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Run the development server (port 5001)

```bash
python main.py
```

Open **http://localhost:5001** in your browser.

### Production

```bash
gunicorn app:app
```

---

## Admin Panel

- URL: **http://localhost:5001/admin**
- Default password: `admin1234` (change via `ADMIN_PASSWORD` env var)

Capabilities: full product and category CRUD, user management, order overview, low-stock warnings, and an analytics dashboard.

---

## User Accounts

Users register with an email address and password. A verification link is sent via email (expires in 24 hours). Passwords are hashed with bcrypt. The session key `user_id` identifies logged-in users; the `@user_login_required` decorator protects user routes.

---

## Image Auto-Fetch

1. Get a free Unsplash API key at https://unsplash.com/developers
2. Add it to `.env` as `UNSPLASH_ACCESS_KEY`
3. When creating/editing an item, leave "Image URL" blank and click **Auto-fetch**

**Fallback chain:** Unsplash → DuckDuckGo image search → `picsum.photos` placeholder.

---

## MongoDB Collections

| Collection | Purpose |
|------------|---------|
| `items` | Product inventory |
| `categories` | Product categories (referenced by items) |
| `users` | User accounts (bcrypt-hashed passwords, verification tokens) |
| `orders` | Order history with line items and shipping address |
| `item_views` | Per-item view/click events for analytics |

### Item schema

```json
{
  "_id": "ObjectId",
  "name": "USB-C Hub 7-in-1",
  "description": "Multiport adapter with HDMI...",
  "category": "Adapters",
  "category_id": "ObjectId",
  "price": 39.99,
  "cost": 18.00,
  "stock": 42,
  "image_url": "https://...",
  "colors_enabled": true,
  "colors": ["Black", "Silver"],
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MONGO_URI` | Yes | — | MongoDB Atlas connection string |
| `SECRET_KEY` | Yes | — | Flask session signing key |
| `ADMIN_PASSWORD` | No | `admin1234` | Admin panel password |
| `UNSPLASH_ACCESS_KEY` | No | — | Enables Unsplash image search |
| `MAIL_SERVER` | No | `localhost` | SMTP server host |
| `MAIL_PORT` | No | `25` | SMTP port |
| `MAIL_USE_TLS` | No | `False` | Enable TLS |
| `MAIL_USERNAME` | No | — | SMTP username |
| `MAIL_PASSWORD` | No | — | SMTP password |
| `MAIL_DEFAULT_SENDER` | No | — | From address for outgoing mail |

---

## Key URLs

| URL | Description |
|-----|-------------|
| `http://localhost:5001/` | Storefront |
| `http://localhost:5001/admin` | Admin panel |
| `http://localhost:5001/register` | User registration |
| `http://localhost:5001/login` | User login |
| `http://localhost:5001/cart` | Shopping cart |
