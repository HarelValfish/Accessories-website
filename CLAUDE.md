# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (use venv)
pip install -r requirements.txt

# Run the development server (port 5001)
python main.py

# Production
gunicorn app:app
```

There are no tests or linters configured in this project.

## Architecture

**TechDen** is a Flask e-commerce app for computer accessories backed by MongoDB Atlas.

### Entry point and app factory

`main.py` is the entry point. It loads `.env`, calls `create_app()` from `app.py`, seeds demo data via `seed_demo_data()`, and starts the dev server. `app.py` is a pure factory — it creates the Flask app, registers extensions (bcrypt, CSRF, mail), and mounts blueprints. It defines no routes.

### Blueprint layout (all routes in `routes.py`)

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `public_bp` | `/` | Storefront, item detail |
| `auth_bp` | `/admin/login`, `/admin/logout` | Admin session auth |
| `admin_bp` | `/admin/...` | Admin CRUD (items, users, orders) |
| `api_bp` | `/api/...` | JSON endpoints (image fetch, categories) |
| `user_bp` | `/register`, `/login`, `/cart`, `/checkout`, `/account`, `/orders` | User accounts and shopping |

### Data layer separation

- `models.py` — product `items` and `categories` CRUD, image auto-fetch, demo seed
- `user_models.py` — `users` and `orders` CRUD
- `database.py` — single shared `MongoClient`; imports `items_collection`, `users_collection`, `orders_collection`, `categories_collection` from here
- `cart_helpers.py` — cart stored entirely in Flask session (not DB)

### Authentication: two separate systems

- **Admin**: plain-text password comparison in `auth.py` (`ADMIN_PASSWORD` env var); session key `admin_logged_in`; decorator `@login_required`
- **Users**: bcrypt-hashed passwords, email verification (24-hour token), stored in MongoDB; session key `user_id`; decorator `@user_login_required` from `user_auth.py`

### Item schema (MongoDB `techden.items`)

Items store both `category_id` (ObjectId ref) and a denormalized `category` name string. The `colors_enabled` / `colors` fields support color variants. `decrement_stock` uses an atomic `$gte` filter to prevent overselling.

### Image fetch cascade

`fetch_image()` in `models.py` tries: (1) Unsplash API if `UNSPLASH_ACCESS_KEY` is set, (2) DuckDuckGo image search via `ddgs`, (3) picsum.photos placeholder.

### Email

`email_service.py` uses Flask-Mail. Verification tokens are 24-hour URL-safe secrets. Order confirmation emails include a shipping address block. All mail config comes from env vars (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`).

## Environment variables

Copy `.env.example` to `.env`. Required: `MONGO_URI`, `SECRET_KEY`. Optional: `ADMIN_PASSWORD` (default `admin1234`), `UNSPLASH_ACCESS_KEY`, and all `MAIL_*` vars.

## Key URLs

- Storefront: `http://localhost:5001/`
- Admin panel: `http://localhost:5001/admin` (password from `ADMIN_PASSWORD`)
