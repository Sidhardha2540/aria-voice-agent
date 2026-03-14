"""
Async SQLite database wrapper for Aria.
Uses aiosqlite so we never block the event loop (critical for real-time voice).
"""
import json
import os
from pathlib import Path

import aiosqlite

from agent.config import DB_PATH
from agent.database.models import Doctor, Appointment, Caller, ClinicInfo


class AsyncDatabase:
    """
    Handles all database operations for the voice agent.
    All methods are async — never use blocking sqlite3 directly in a voice pipeline!
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_PATH

    async def connect(self) -> None:
        """Ensure the data directory exists and connect to SQLite."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row  # access columns by name
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialization TEXT NOT NULL,
                available_days TEXT NOT NULL,
                slot_duration_minutes INTEGER DEFAULT 30
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                doctor_id INTEGER NOT NULL,
                patient_name TEXT NOT NULL,
                patient_phone TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'booked',
                created_at TEXT NOT NULL,
                notes TEXT DEFAULT '',
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            );
            CREATE TABLE IF NOT EXISTS callers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE NOT NULL,
                name TEXT DEFAULT '',
                last_call_at TEXT NOT NULL,
                preferences TEXT DEFAULT '{}',
                call_count INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS clinic_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if hasattr(self, "_conn"):
            await self._conn.close()

    # ——— Doctors ———
    async def get_all_doctors(self) -> list[Doctor]:
        """Fetch all doctors."""
        async with self._conn.execute("SELECT * FROM doctors") as cur:
            rows = await cur.fetchall()
        return [
            Doctor(
                id=r["id"],
                name=r["name"],
                specialization=r["specialization"],
                available_days=json.loads(r["available_days"]),
                slot_duration_minutes=r["slot_duration_minutes"],
            )
            for r in rows
        ]

    async def get_doctor_by_id(self, doctor_id: int) -> Doctor | None:
        """Fetch a doctor by ID."""
        async with self._conn.execute(
            "SELECT * FROM doctors WHERE id = ?", (doctor_id,)
        ) as cur:
            r = await cur.fetchone()
        if r is None:
            return None
        return Doctor(
            id=r["id"],
            name=r["name"],
            specialization=r["specialization"],
            available_days=json.loads(r["available_days"]),
            slot_duration_minutes=r["slot_duration_minutes"],
        )

    async def get_doctors_by_name_or_specialization(self, query: str) -> list[Doctor]:
        """Fuzzy match by name or specialization."""
        all_doctors = await self.get_all_doctors()
        q = query.lower().strip()
        return [
            d
            for d in all_doctors
            if q in d.name.lower() or q in d.specialization.lower()
        ]

    # ——— Appointments ———
    async def get_appointments_by_doctor_and_date(
        self, doctor_id: int, date: str
    ) -> list[Appointment]:
        """Get booked appointments for a doctor on a date."""
        async with self._conn.execute(
            """SELECT * FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND status = 'booked'
               ORDER BY start_time""",
            (doctor_id, date),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_appointment(r) for r in rows]

    async def get_appointment_by_id(self, appointment_id: str) -> Appointment | None:
        """Fetch appointment by ID (e.g. APT-1234)."""
        async with self._conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ) as cur:
            r = await cur.fetchone()
        return self._row_to_appointment(r) if r else None

    async def create_appointment(
        self,
        appointment_id: str,
        doctor_id: int,
        patient_name: str,
        patient_phone: str,
        date: str,
        start_time: str,
        end_time: str,
        notes: str = "",
    ) -> None:
        """Insert a new appointment."""
        from datetime import datetime

        created_at = datetime.utcnow().isoformat() + "Z"
        await self._conn.execute(
            """INSERT INTO appointments
               (id, doctor_id, patient_name, patient_phone, appointment_date,
                start_time, end_time, status, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'booked', ?, ?)""",
            (
                appointment_id,
                doctor_id,
                patient_name,
                patient_phone,
                date,
                start_time,
                end_time,
                created_at,
                notes,
            ),
        )
        await self._conn.commit()

    async def update_appointment_status(
        self, appointment_id: str, status: str
    ) -> bool:
        """Update appointment status (e.g. to 'cancelled')."""
        cur = await self._conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status, appointment_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def reschedule_appointment(
        self, appointment_id: str, new_date: str, new_time: str, new_end_time: str
    ) -> bool:
        """Reschedule an appointment."""
        cur = await self._conn.execute(
            """UPDATE appointments
               SET appointment_date = ?, start_time = ?, end_time = ?
               WHERE id = ?""",
            (new_date, new_time, new_end_time, appointment_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    def _row_to_appointment(self, r) -> Appointment:
        return Appointment(
            id=r["id"],
            doctor_id=r["doctor_id"],
            patient_name=r["patient_name"],
            patient_phone=r["patient_phone"],
            appointment_date=r["appointment_date"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            status=r["status"],
            created_at=r["created_at"],
            notes=r["notes"] or "",
        )

    # ——— Callers ———
    async def get_caller_by_phone(self, phone_number: str) -> Caller | None:
        """Look up caller by phone."""
        async with self._conn.execute(
            "SELECT * FROM callers WHERE phone_number = ?", (phone_number,)
        ) as cur:
            r = await cur.fetchone()
        if r is None:
            return None
        return Caller(
            id=r["id"],
            phone_number=r["phone_number"],
            name=r["name"] or "",
            last_call_at=r["last_call_at"],
            preferences=json.loads(r["preferences"] or "{}"),
            call_count=r["call_count"],
        )

    async def upsert_caller(
        self, phone_number: str, name: str = "", preferences: dict | None = None
    ) -> None:
        """Create or update a caller record."""
        from datetime import datetime

        now = datetime.utcnow().isoformat() + "Z"
        prefs = json.dumps(preferences or {})

        await self._conn.execute(
            """INSERT INTO callers (phone_number, name, last_call_at, preferences, call_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(phone_number) DO UPDATE SET
                 name = COALESCE(excluded.name, name),
                 last_call_at = excluded.last_call_at,
                 call_count = call_count + 1,
                 preferences = COALESCE(excluded.preferences, preferences)""",
            (phone_number, name, now, prefs),
        )
        await self._conn.commit()

    async def update_caller_preferences(
        self, phone_number: str, key: str, value: str
    ) -> bool:
        """Update a caller's preference."""
        caller = await self.get_caller_by_phone(phone_number)
        if not caller:
            return False
        prefs = caller.preferences.copy()
        prefs[key] = value
        await self._conn.execute(
            "UPDATE callers SET preferences = ? WHERE phone_number = ?",
            (json.dumps(prefs), phone_number),
        )
        await self._conn.commit()
        return True

    # ——— Clinic info ———
    async def get_clinic_info(self, key: str) -> str | None:
        """Get a clinic info value by key."""
        async with self._conn.execute(
            "SELECT value FROM clinic_info WHERE key = ?", (key,)
        ) as cur:
            r = await cur.fetchone()
        return r["value"] if r else None

    async def set_clinic_info(self, key: str, value: str) -> None:
        """Set a clinic info value."""
        await self._conn.execute(
            """INSERT INTO clinic_info (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        await self._conn.commit()
