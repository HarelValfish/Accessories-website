"""
main.py
───────
Entry point for the TechDen application.

Run this file to start the development server:
    python main.py

This file's only jobs are:
  1. Call create_app() from app.py to get the configured Flask instance
  2. Call seed_demo_data() from models.py to populate the DB on first run
  3. Start the Flask development server

Keep this file minimal — all real logic lives in the other modules.
"""

from dotenv import load_dotenv
load_dotenv()                       # load .env file before anything else reads os.environ

from app    import create_app
from models import seed_demo_data


# ── Build the app ──────────────────────────────────────────────────────────────
app = create_app()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    seed_demo_data()
    app.run(debug=True, port=5001)
