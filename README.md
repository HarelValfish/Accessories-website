# TechDen — Computer Accessories Store

A full-stack Flask web app for selling computer accessories with a password-protected admin panel connected to MongoDB.

---

## Features

- **Storefront** — Grid of products with images, prices, stock status, category filters, and search
- **Item detail page** — Full product info, stock level, item ID
- **Admin panel** — Password-protected dashboard with full CRUD (create, read, update, delete)
- **Auto image fetch** — When creating an item, click "Auto-fetch" to pull an image from Unsplash based on product name/description
- **MongoDB** — All items stored in MongoDB (`techden` database, `items` collection)
- **Demo data** — 8 sample items seeded automatically on first run

---

## Project Structure

```
techden/
├── app.py                  # Main Flask app (routes, DB logic, image fetch)
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── templates/
│   ├── base.html           # Shared nav + footer layout
│   ├── index.html          # Public storefront
│   ├── item_detail.html    # Single item page
│   ├── admin_login.html    # Admin login
│   ├── admin_dashboard.html# Admin inventory table
│   └── admin_item_form.html# Create / edit item form
└── static/
    └── css/
        └── style.css       # Full stylesheet
```

---

## Setup & Run

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start MongoDB

Make sure MongoDB is running locally:
```bash
mongod --dbpath /data/db
```

Or use a MongoDB Atlas connection string (see `.env.example`).

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
export $(cat .env | xargs)
```

### 4. Run the app

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Admin Panel

- URL: **http://localhost:5000/admin**
- Default password: `admin1234` (change via `ADMIN_PASSWORD` env var)

### Admin capabilities:
- View all items with ID, name, category, price, stock
- Create new items — with auto image fetch from Unsplash
- Edit any item
- Delete items
- Low-stock warnings (≤ 5 units)

---

## Image Auto-Fetch

1. Get a free Unsplash API key at https://unsplash.com/developers
2. Add it to your `.env` as `UNSPLASH_ACCESS_KEY`
3. When creating/editing an item, leave "Image URL" blank and click **🔍 Auto-fetch** — it will search Unsplash using the product name and description

Without an Unsplash key, the app falls back to random placeholder images (still functional).

---

## MongoDB Schema

Each item document in the `items` collection:

```json
{
  "_id": "ObjectId",
  "name": "USB-C Hub 7-in-1",
  "description": "Multiport adapter with HDMI...",
  "category": "Adapters",
  "price": 39.99,
  "stock": 42,
  "image_url": "https://...",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

---

## Production Notes

- Change `SECRET_KEY` and `ADMIN_PASSWORD` to secure values
- Use MongoDB Atlas for a hosted database
- Deploy with Gunicorn: `gunicorn app:app`
- Consider adding HTTPS and rate limiting for the admin login route
