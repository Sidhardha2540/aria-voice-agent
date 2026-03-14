"""
Clinic info tool — FAQs, hours, address, insurance, services.
"""
from agent.config import DB_PATH
from agent.database.db import AsyncDatabase

_db: AsyncDatabase | None = None


async def _get_db() -> AsyncDatabase:
    global _db
    if _db is None:
        _db = AsyncDatabase(DB_PATH)
        await _db.connect()
    return _db


# Map common topics to DB keys
TOPIC_MAP = {
    "hours": "hours",
    "time": "hours",
    "open": "hours",
    "when": "hours",
    "address": "address",
    "location": "address",
    "where": "address",
    "directions": "address",
    "insurance": "insurance",
    "services": "services",
    "parking": "parking",
    "general": "general",
    "hello": "general",
    "hi": "general",
}


async def get_clinic_info(topic: str) -> str:
    """
    Get clinic information by topic.

    Args:
        topic: One of: hours, address, insurance, services, parking, general.
    """
    db = await _get_db()
    t = (topic or "").strip().lower()
    key = TOPIC_MAP.get(t, t) if t else "general"
    val = await db.get_clinic_info(key)
    if val:
        return val
    return "I don't have specific info on that, but our front desk can definitely help."
