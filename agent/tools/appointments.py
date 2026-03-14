"""
Appointment tools for Aria — check availability, book, reschedule, cancel.
Each tool is an async function compatible with Pipecat's function-calling.
"""
import random
from datetime import date, datetime, timedelta

from agent.config import DB_PATH
from agent.database.db import AsyncDatabase


_db: AsyncDatabase | None = None


async def _get_db() -> AsyncDatabase:
    global _db
    if _db is None:
        _db = AsyncDatabase(DB_PATH)
        await _db.connect()
    return _db


def _parse_date(s: str) -> date | None:
    """Parse date string (YYYY-MM-DD or 'next available') to date object."""
    s = (s or "").strip().lower()
    if not s or s == "next available":
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _time_str(h: int, m: int = 0) -> str:
    return f"{h:02d}:{m:02d}:00"


def _format_time_display(t: str) -> str:
    """Convert HH:MM:SS to natural '10:30 AM'."""
    try:
        parts = t.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if h == 0:
            return f"12:{m:02d} AM"
        if h < 12:
            return f"{h}:{m:02d} AM"
        if h == 12:
            return f"12:{m:02d} PM"
        return f"{h - 12}:{m:02d} PM"
    except (ValueError, IndexError):
        return t


def _format_date_display(d: date) -> str:
    """e.g. Jan 15."""
    return d.strftime("%b %d")


async def check_availability(doctor_name_or_specialization: str, preferred_date: str = "next available") -> str:
    """
    Check available appointment slots for a doctor.

    Args:
        doctor_name_or_specialization: Doctor name (e.g. "Dr. Chen") or specialization (e.g. "dermatology").
        preferred_date: Preferred date as YYYY-MM-DD, or "next available" for next 5 business days.
    """
    db = await _get_db()
    doctors = await db.get_doctors_by_name_or_specialization(doctor_name_or_specialization)
    if not doctors:
        return f"I couldn't find a doctor matching '{doctor_name_or_specialization}'. We have General, Cardiology, Dermatology, and Pediatrics."

    slot_duration = 30
    start_hour, end_hour = 9, 17

    # Determine which dates to check
    today = date.today()
    if preferred_date and preferred_date.lower() != "next available":
        target = _parse_date(preferred_date)
        if target:
            dates_to_check = [target]
        else:
            dates_to_check = []
            for i in range(10):
                d = today + timedelta(days=i)
                if d.weekday() < 5:
                    dates_to_check.append(d)
                    if len(dates_to_check) >= 5:
                        break
    else:
        dates_to_check = []
        for i in range(14):
            d = today + timedelta(days=i)
            if d.weekday() < 5:
                dates_to_check.append(d)
                if len(dates_to_check) >= 5:
                    break

    if not dates_to_check:
        return "I couldn't find any weekdays to check. Please specify a date."

    results = []
    for doc in doctors:
        for d in dates_to_check:
            day_name = d.strftime("%A")
            if day_name not in doc.available_days:
                continue

            existing = await db.get_appointments_by_doctor_and_date(doc.id, d.isoformat())
            booked_times = {
                (a.start_time, a.end_time)
                for a in existing
            }

            slots = []
            t = datetime.combine(d, datetime.min.time().replace(hour=start_hour, minute=0))
            end_dt = datetime.combine(d, datetime.min.time().replace(hour=end_hour, minute=0))
            while t + timedelta(minutes=slot_duration) <= end_dt:
                start_s = _time_str(t.hour, t.minute)
                end_s = _time_str((t + timedelta(minutes=slot_duration)).hour, (t + timedelta(minutes=slot_duration)).minute)
                if (start_s, end_s) not in booked_times:
                    slots.append((d, start_s, _format_time_display(start_s)))
                t += timedelta(minutes=slot_duration)

            if slots:
                by_date = {}
                for d, _, disp in slots:
                    key = d.isoformat()
                    if key not in by_date:
                        by_date[key] = []
                    by_date[key].append(disp)
                for iso_date in sorted(by_date.keys()):
                    dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
                    times = ", ".join(sorted(by_date[iso_date], key=lambda x: x))
                    results.append(f"{doc.name} on {_format_date_display(dt)}: {times}")

    if not results:
        return f"{doctors[0].name} is fully booked for the dates I checked. Would you like me to try another week or a different doctor?"

    return "Available slots: " + "; ".join(results[:5])


async def book_appointment(doctor_id: int, patient_name: str, patient_phone: str, date: str, time: str, notes: str = "") -> str:
    """
    Book an appointment.

    Args:
        doctor_id: ID of the doctor (1-4).
        patient_name: Patient's full name.
        patient_phone: Patient's phone number.
        date: Date as YYYY-MM-DD.
        time: Time as HH:MM or HH:MM:SS.
        notes: Optional notes (e.g. reason for visit).
    """
    db = await _get_db()
    doctor = await db.get_doctor_by_id(doctor_id)
    if not doctor:
        return "I couldn't find that doctor. Please try again."

    # Normalize time
    if len(time) == 5:
        time = time + ":00"
    start_time = time
    start_dt = datetime.strptime(time, "%H:%M:%S")
    end_dt = start_dt + timedelta(minutes=30)
    end_time = _time_str(end_dt.hour, end_dt.minute)

    # Verify slot still available
    existing = await db.get_appointments_by_doctor_and_date(doctor_id, date)
    for a in existing:
        if a.start_time == start_time:
            return "I'm sorry, that slot was just taken. Let me find another for you."

    apt_id = f"APT-{random.randint(1000, 9999)}"
    await db.create_appointment(
        appointment_id=apt_id,
        doctor_id=doctor_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        date=date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
    )
    await db.upsert_caller(patient_phone, patient_name)

    d = datetime.strptime(date, "%Y-%m-%d").date()
    return f"Appointment booked: {doctor.name} on {d.strftime('%A')} {_format_date_display(d)} at {_format_time_display(start_time)} for {patient_name}. Appointment ID: {apt_id}."


async def reschedule_appointment(appointment_id: str, new_date: str, new_time: str) -> str:
    """
    Reschedule an existing appointment.

    Args:
        appointment_id: The appointment ID (e.g. APT-1234).
        new_date: New date as YYYY-MM-DD.
        new_time: New time as HH:MM or HH:MM:SS.
    """
    db = await _get_db()
    apt = await db.get_appointment_by_id(appointment_id)
    if not apt:
        return f"I couldn't find appointment {appointment_id}. Please check the ID."

    if len(new_time) == 5:
        new_time = new_time + ":00"
    end_dt = datetime.strptime(new_time, "%H:%M:%S") + timedelta(minutes=30)
    new_end = _time_str(end_dt.hour, end_dt.minute)

    # Verify new slot available
    existing = await db.get_appointments_by_doctor_and_date(apt.doctor_id, new_date)
    for a in existing:
        if a.id != appointment_id and a.start_time == new_time:
            return "That slot is no longer available. Let me find another."

    doctor = await db.get_doctor_by_id(apt.doctor_id)
    old_info = f"{apt.appointment_date} at {_format_time_display(apt.start_time)}"
    await db.reschedule_appointment(appointment_id, new_date, new_time, new_end)

    d = datetime.strptime(new_date, "%Y-%m-%d").date()
    return f"Rescheduled! {doctor.name if doctor else 'Your'} appointment is now on {d.strftime('%A')} {_format_date_display(d)} at {_format_time_display(new_time)}. (Previously: {old_info})"


async def cancel_appointment(appointment_id: str, reason: str = "") -> str:
    """
    Cancel an appointment.

    Args:
        appointment_id: The appointment ID (e.g. APT-1234).
        reason: Optional reason for cancellation.
    """
    db = await _get_db()
    apt = await db.get_appointment_by_id(appointment_id)
    if not apt:
        return f"I couldn't find appointment {appointment_id}. Please check the ID."

    success = await db.update_appointment_status(appointment_id, "cancelled")
    if success:
        return f"Appointment {appointment_id} has been cancelled. We hope to see you soon!"
    return f"I had trouble cancelling {appointment_id}. Please call our front desk."
