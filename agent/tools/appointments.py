"""
Appointment tools for Aria — check availability, book, reschedule, cancel.
Each tool is an async function compatible with Pipecat's function-calling.
"""
import random
from difflib import get_close_matches
from datetime import date, datetime, timedelta

from agent.database.db import get_shared_db
from agent.database.models import Doctor


def _fuzzy_doctor_matches(query: str, all_doctors: list[Doctor], limit: int = 3) -> list[Doctor]:
    """Return closest doctor matches by name or specialization when exact match fails."""
    q = query.lower().strip()
    if not q:
        return []
    names = [d.name for d in all_doctors]
    specs = list({d.specialization for d in all_doctors})
    candidates = names + specs
    matches = get_close_matches(q, [c.lower() for c in candidates], n=limit * 2, cutoff=0.4)
    result = []
    seen_ids = set()
    for m in matches:
        for d in all_doctors:
            if d.id not in seen_ids and (m == d.name.lower() or m == d.specialization.lower()):
                result.append(d)
                seen_ids.add(d.id)
                if len(result) >= limit:
                    return result
    # Fallback: any doctor if query is very short or partial
    if not result and all_doctors:
        for d in all_doctors:
            if q[0] in d.name.lower() or q[:3] in d.specialization.lower():
                result.append(d)
                if len(result) >= limit:
                    break
    return result[:limit]


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


def _is_weekend_request(date_str: str) -> bool:
    """Check if user requested a weekend day (we're weekdays-only)."""
    s = (date_str or "").strip().lower()
    return any(d in s for d in ["saturday", "sunday", "sat", "sun"])


async def check_availability(doctor_name_or_specialization: str, preferred_date: str = "next available") -> str:
    """
    Check available appointment slots for a doctor.

    Args:
        doctor_name_or_specialization: Doctor name (e.g. "Dr. Chen") or specialization (e.g. "dermatology").
        preferred_date: Preferred date as YYYY-MM-DD, or "next available" for next 3 business days.
    """
    db = await get_shared_db()
    doctors = await db.get_doctors_by_name_or_specialization(doctor_name_or_specialization)

    # Fuzzy match when no exact match — return closest options for LLM to offer
    if not doctors:
        all_doctors = await db.get_all_doctors()
        fuzzy = _fuzzy_doctor_matches(doctor_name_or_specialization, all_doctors, limit=3)
        if fuzzy:
            opts = ", ".join(f"{d.name} ({d.specialization})" for d in fuzzy)
            return f"No exact match for '{doctor_name_or_specialization}'. Closest options: {opts}. Which one did you mean?"
        return "No doctor found. We have General, Cardiology, Dermatology, and Pediatrics. Which specialty or doctor would you like?"

    # Weekend requested but doctors are weekdays-only
    if _is_weekend_request(preferred_date):
        today = date.today()
        next_fri = today
        while next_fri.weekday() != 4:
            next_fri += timedelta(days=1)
        next_mon = next_fri + timedelta(days=3)
        return f"Our doctors aren't available on weekends. Would you like Friday {next_fri.strftime('%b %d')} or Monday {next_mon.strftime('%b %d')} instead?"

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
                    if len(dates_to_check) >= 3:
                        break
    else:
        dates_to_check = []
        for i in range(14):
            d = today + timedelta(days=i)
            if d.weekday() < 5:
                dates_to_check.append(d)
                if len(dates_to_check) >= 3:
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
        all_docs = await db.get_all_doctors()
        others = [d.name for d in all_docs if d.id != doctors[0].id][:2]
        opts = f"Would you like me to check Friday, try next week, or book with {others[0]}" + (f" or {others[1]}" if len(others) > 1 else "") + "?"
        return f"{doctors[0].name} doesn't have openings for those dates. {opts}"

    return "Available slots: " + "; ".join(results[:3])


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
    db = await get_shared_db()
    doctor = await db.get_doctor_by_id(doctor_id)
    if not doctor:
        all_doctors = await db.get_all_doctors()
        fuzzy = _fuzzy_doctor_matches(str(doctor_id), all_doctors, limit=3)
        if fuzzy:
            opts = ", ".join(f"{d.name} ({d.specialization})" for d in fuzzy)
            return f"That doctor ID wasn't found. Did you mean one of these? {opts}"
        return "That doctor isn't in our system. We have General, Cardiology, Dermatology, and Pediatrics. Which would you like?"

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
    await db.update_caller_preferences(patient_phone, "last_doctor", doctor.name)

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
    db = await get_shared_db()
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
    db = await get_shared_db()
    apt = await db.get_appointment_by_id(appointment_id)
    if not apt:
        return f"I couldn't find appointment {appointment_id}. Please check the ID."

    success = await db.update_appointment_status(appointment_id, "cancelled")
    if success:
        return f"Appointment {appointment_id} has been cancelled. We hope to see you soon!"
    return f"I had trouble cancelling {appointment_id}. Please call our front desk."
