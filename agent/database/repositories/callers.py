"""
Caller repository — pure data access.
"""
import json
from datetime import datetime

from agent.database.manager import DatabaseManager
from agent.database.models import Caller


class CallerRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_by_phone(self, phone_number: str) -> Caller | None:
        row = await self._db.execute_one(
            "SELECT * FROM callers WHERE phone_number = ?", phone_number
        )
        return self._row_to_caller(row) if row else None

    async def upsert(
        self,
        phone_number: str,
        name: str = "",
        preferences: dict | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        prefs = json.dumps(preferences or {})
        await self._db.execute_write(
            """INSERT INTO callers (phone_number, name, last_call_at, preferences, call_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(phone_number) DO UPDATE SET
                 name = COALESCE(excluded.name, callers.name),
                 last_call_at = excluded.last_call_at,
                 call_count = callers.call_count + 1,
                 preferences = COALESCE(excluded.preferences, callers.preferences)""",
            phone_number,
            name,
            now,
            prefs,
        )

    async def update_preferences(
        self, phone_number: str, key: str, value: str
    ) -> bool:
        caller = await self.get_by_phone(phone_number)
        if not caller:
            return False
        prefs = caller.preferences.copy()
        prefs[key] = value
        await self._db.execute_write(
            "UPDATE callers SET preferences = ? WHERE phone_number = ?",
            json.dumps(prefs),
            phone_number,
        )
        return True

    def _row_to_caller(self, row: dict) -> Caller:
        prefs = row.get("preferences") or "{}"
        if isinstance(prefs, str):
            prefs = json.loads(prefs)
        return Caller(
            id=row["id"],
            phone_number=row["phone_number"],
            name=row.get("name") or "",
            last_call_at=row["last_call_at"],
            preferences=prefs,
            call_count=row.get("call_count", 1),
        )
