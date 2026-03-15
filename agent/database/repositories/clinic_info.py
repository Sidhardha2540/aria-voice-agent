"""
Clinic info repository — key/value store for FAQs, hours, etc.
"""
from agent.database.manager import DatabaseManager
from agent.database.models import ClinicInfo


class ClinicInfoRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        row = await self._db.execute_one(
            "SELECT value FROM clinic_info WHERE key = ?", key
        )
        return row["value"] if row else None

    async def set(self, key: str, value: str) -> None:
        await self._db.execute_write(
            """INSERT INTO clinic_info (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            key,
            value,
        )
