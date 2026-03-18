"""
Database access for Aria — single connection via DatabaseManager + repositories.
This module provides backward-compatible get_shared_db() returning an adapter
that delegates to db_manager and repositories. All callers share one connection.
"""
from datetime import datetime

from agent.database.manager import db_manager
from agent.database.models import Doctor, Appointment, Caller, ClinicInfo
from agent.database.repositories import (
    DoctorRepository,
    AppointmentRepository,
    CallerRepository,
    ClinicInfoRepository,
)

_shared_instance = None


async def get_shared_db() -> "SharedDbAdapter":
    """Shared DB adapter — one connection (db_manager), pre-initialized on first call."""
    global _shared_instance
    if _shared_instance is None:
        await db_manager.startup()
        _shared_instance = SharedDbAdapter()
    return _shared_instance


class SharedDbAdapter:
    """
    Backward-compatible adapter: same interface as the old AsyncDatabase.
    Delegates to db_manager and repositories. Use get_shared_db() to obtain it.
    """

    def __init__(self) -> None:
        self._doctors = DoctorRepository(db_manager)
        self._appointments = AppointmentRepository(db_manager)
        self._callers = CallerRepository(db_manager)
        self._clinic = ClinicInfoRepository(db_manager)

    # ——— Doctors ———
    async def get_all_doctors(self) -> list[Doctor]:
        return await self._doctors.get_all()

    async def get_doctor_by_id(self, doctor_id: int) -> Doctor | None:
        return await self._doctors.get_by_id(doctor_id)

    async def get_doctors_by_name_or_specialization(self, query: str) -> list[Doctor]:
        return await self._doctors.get_by_name_or_specialization(query)

    # ——— Appointments ———
    async def get_appointments_by_doctor_and_date(
        self, doctor_id: int, date: str
    ) -> list[Appointment]:
        return await self._appointments.get_by_doctor_and_date(doctor_id, date)

    async def get_appointments_by_patient_phone(
        self, patient_phone: str, future_only: bool = True
    ) -> list[Appointment]:
        return await self._appointments.get_by_patient_phone(
            patient_phone, future_only=future_only
        )

    async def get_appointment_by_id(self, appointment_id: str) -> Appointment | None:
        return await self._appointments.get_by_id(appointment_id)

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
        from agent.database.models import AppointmentStatus

        created_at = datetime.utcnow().isoformat() + "Z"
        apt = Appointment(
            id=appointment_id,
            doctor_id=doctor_id,
            patient_name=patient_name,
            patient_phone=patient_phone,
            appointment_date=date,
            start_time=start_time,
            end_time=end_time,
            status=AppointmentStatus.BOOKED,
            created_at=created_at,
            notes=notes,
        )
        await self._appointments.create(apt)

    async def update_appointment_status(
        self, appointment_id: str, status: str
    ) -> bool:
        return await self._appointments.update_status(appointment_id, status)

    async def reschedule_appointment(
        self, appointment_id: str, new_date: str, new_time: str, new_end_time: str
    ) -> bool:
        return await self._appointments.reschedule(
            appointment_id, new_date, new_time, new_end_time
        )

    # ——— Callers ———
    async def get_caller_by_phone(self, phone_number: str) -> Caller | None:
        return await self._callers.get_by_phone(phone_number)

    async def upsert_caller(
        self, phone_number: str, name: str = "", preferences: dict | None = None
    ) -> None:
        await self._callers.upsert(phone_number, name, preferences)

    async def update_caller_preferences(
        self, phone_number: str, key: str, value: str
    ) -> bool:
        return await self._callers.update_preferences(phone_number, key, value)

    # ——— Clinic info ———
    async def get_clinic_info(self, key: str) -> str | None:
        return await self._clinic.get(key)

    async def set_clinic_info(self, key: str, value: str) -> None:
        await self._clinic.set(key, value)

    async def close(self) -> None:
        """No-op: connection lifecycle is managed by db_manager in main."""
        pass


# Legacy name for code that might reference AsyncDatabase
AsyncDatabase = SharedDbAdapter
