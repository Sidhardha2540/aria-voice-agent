"""
Doctor repository — pure data access, no business logic.
Uses the shared DatabaseManager, never creates its own connection.
"""
import json

from agent.database.manager import DatabaseManager
from agent.database.models import Doctor


class DoctorRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def add(
        self,
        name: str,
        specialization: str,
        available_days: list[str],
        slot_duration_minutes: int = 30,
    ) -> None:
        """Insert a doctor (id is auto-generated)."""
        days_json = json.dumps(available_days)
        await self._db.execute_write(
            """INSERT INTO doctors (name, specialization, available_days, slot_duration_minutes)
               VALUES (?, ?, ?, ?)""",
            name,
            specialization,
            days_json,
            slot_duration_minutes,
        )

    async def get_all(self) -> list[Doctor]:
        rows = await self._db.execute("SELECT * FROM doctors")
        return [self._row_to_doctor(r) for r in rows]

    async def get_by_id(self, doctor_id: int) -> Doctor | None:
        row = await self._db.execute_one("SELECT * FROM doctors WHERE id = ?", doctor_id)
        return self._row_to_doctor(row) if row else None

    async def get_by_name_or_specialization(self, query: str) -> list[Doctor]:
        all_doctors = await self.get_all()
        q = query.lower().strip()
        return [
            d for d in all_doctors
            if q in d.name.lower() or q in d.specialization.lower()
        ]

    def _row_to_doctor(self, row: dict) -> Doctor:
        available_days = row.get("available_days")
        if isinstance(available_days, str):
            available_days = json.loads(available_days)
        return Doctor(
            id=row["id"],
            name=row["name"],
            specialization=row["specialization"],
            available_days=available_days,
            slot_duration_minutes=row.get("slot_duration_minutes", 30),
        )
