"""
Appointment repository — pure data access, no business logic.
"""
from agent.database.manager import DatabaseManager
from agent.database.models import Appointment


class AppointmentRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def get_by_id(self, appointment_id: str) -> Appointment | None:
        row = await self._db.execute_one(
            "SELECT * FROM appointments WHERE id = ?", appointment_id
        )
        return self._row_to_appointment(row) if row else None

    async def get_by_doctor_and_date(
        self, doctor_id: int, date: str
    ) -> list[Appointment]:
        rows = await self._db.execute(
            """SELECT * FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND status = 'booked'
               ORDER BY start_time""",
            doctor_id,
            date,
        )
        return [self._row_to_appointment(r) for r in rows]

    async def get_booked_slots_batch(
        self, doctor_ids: list[int], dates: list[str]
    ) -> dict[tuple[int, str], set[str]]:
        """One query: (doctor_id, appointment_date) -> set of start_time for booked rows."""
        if not doctor_ids or not dates:
            return {}
        q_marks = ",".join("?" * len(doctor_ids))
        d_marks = ",".join("?" * len(dates))
        sql = f"""SELECT doctor_id, appointment_date, start_time FROM appointments
                  WHERE status = 'booked' AND doctor_id IN ({q_marks})
                  AND appointment_date IN ({d_marks})"""
        rows = await self._db.execute(sql, *doctor_ids, *dates)
        out: dict[tuple[int, str], set[str]] = {}
        for r in rows:
            key = (int(r["doctor_id"]), r["appointment_date"])
            out.setdefault(key, set()).add(r["start_time"])
        return out

    async def get_by_patient_phone(
        self, patient_phone: str, future_only: bool = True
    ) -> list[Appointment]:
        """List appointments for a patient by phone. Optionally only future (date >= today)."""
        if future_only:
            rows = await self._db.execute(
                """SELECT * FROM appointments
                   WHERE patient_phone = ? AND status = 'booked'
                   AND appointment_date >= date('now')
                   ORDER BY appointment_date, start_time""",
                patient_phone,
            )
        else:
            rows = await self._db.execute(
                """SELECT * FROM appointments
                   WHERE patient_phone = ? AND status = 'booked'
                   ORDER BY appointment_date, start_time""",
                patient_phone,
            )
        return [self._row_to_appointment(r) for r in rows]

    async def create(self, appointment: Appointment) -> None:
        await self._db.execute_write(
            """INSERT INTO appointments
               (id, doctor_id, patient_name, patient_phone, appointment_date,
                start_time, end_time, status, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            appointment.id,
            appointment.doctor_id,
            appointment.patient_name,
            appointment.patient_phone,
            appointment.appointment_date,
            appointment.start_time,
            appointment.end_time,
            getattr(appointment.status, "value", str(appointment.status)),
            appointment.created_at,
            appointment.notes,
        )

    async def update_status(self, appointment_id: str, status: str) -> bool:
        await self._db.execute_write(
            "UPDATE appointments SET status = ? WHERE id = ? AND status = 'booked'",
            status,
            appointment_id,
        )
        row = await self._db.execute_one(
            "SELECT id FROM appointments WHERE id = ? AND status = ?",
            appointment_id,
            status,
        )
        return row is not None

    async def reschedule(
        self, appointment_id: str, new_date: str, new_start: str, new_end: str
    ) -> bool:
        await self._db.execute_write(
            """UPDATE appointments
               SET appointment_date = ?, start_time = ?, end_time = ?
               WHERE id = ?""",
            new_date,
            new_start,
            new_end,
            appointment_id,
        )
        row = await self._db.execute_one(
            "SELECT id FROM appointments WHERE id = ?", appointment_id
        )
        return row is not None

    def _row_to_appointment(self, row: dict) -> Appointment:
        return Appointment(
            id=row["id"],
            doctor_id=row["doctor_id"],
            patient_name=row["patient_name"],
            patient_phone=row["patient_phone"],
            appointment_date=row["appointment_date"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            status=row.get("status", "booked"),
            created_at=row["created_at"],
            notes=row.get("notes") or "",
        )
