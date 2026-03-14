"""
Caller memory tools — remember returning callers.
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


async def lookup_caller(phone_number: str) -> str:
    """
    Look up a caller by phone number to see if they've called before.

    Args:
        phone_number: The caller's phone number.
    """
    db = await _get_db()
    caller = await db.get_caller_by_phone(phone_number)
    if caller:
        return f"Returning caller: {caller.name or 'Unknown'}, last visited {caller.last_call_at[:10]}, {caller.call_count} previous calls. Preferences: {caller.preferences}."
    return "New caller, no previous records."


async def update_caller_preferences(phone_number: str, preference_key: str, preference_value: str) -> str:
    """
    Update a caller's preference for future calls.

    Args:
        phone_number: The caller's phone number.
        preference_key: Key for the preference (e.g. "preferred_doctor", "notes").
        preference_value: Value to store.
    """
    db = await _get_db()
    success = await db.update_caller_preferences(phone_number, preference_key, preference_value)
    if success:
        return f"Preference '{preference_key}' updated for caller."
    return "Caller not found. Could not update preferences."
