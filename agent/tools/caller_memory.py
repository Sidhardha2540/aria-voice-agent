"""
Caller memory tools — remember returning callers and personalize.
"""
from agent.database.db import get_shared_db


async def lookup_caller(phone_number: str) -> str:
    """
    Look up a caller by phone number. Call this as soon as you have their phone.
    For returning callers, use the info to personalize (greet by name, reference last doctor).
    """
    db = await get_shared_db()
    caller = await db.get_caller_by_phone(phone_number)
    if caller:
        prefs = caller.preferences or {}
        last_doctor = prefs.get("last_doctor", "")
        extra = f" Last saw: {last_doctor}." if last_doctor else ""
        return f"Returning caller: {caller.name or 'Unknown'}, last visited {caller.last_call_at[:10]}, {caller.call_count} previous calls. Preferences: {prefs}.{extra}"
    return "New caller, no previous records."


async def save_caller(phone_number: str, name: str = "") -> str:
    """
    Create or update a caller record. Call when a new caller gives their name and phone,
    or when you learn their details during the call (before or after booking).
    """
    db = await get_shared_db()
    await db.upsert_caller(phone_number, name or "")
    return f"Caller saved: {name or 'Unknown'} ({phone_number})."


async def update_caller_preferences(phone_number: str, preference_key: str, preference_value: str) -> str:
    """
    Update a caller's preference for future calls.

    Args:
        phone_number: The caller's phone number.
        preference_key: Key for the preference (e.g. "preferred_doctor", "notes").
        preference_value: Value to store.
    """
    db = await get_shared_db()
    success = await db.update_caller_preferences(phone_number, preference_key, preference_value)
    if success:
        return f"Preference '{preference_key}' updated for caller."
    return "Caller not found. Could not update preferences."
