"""
Run this script to seed the database with demo data.
Usage: uv run python scripts/seed_db.py
"""
import asyncio

from agent.database.seed import seed

if __name__ == "__main__":
    asyncio.run(seed())
