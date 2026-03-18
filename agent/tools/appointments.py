"""
Appointment tools — optimized for voice latency.
Tool results are near-speakable sentences so the LLM can relay them naturally.
"""
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta

from agent.database.db import get_shared_db


def generate_appointment_id() -> str:
    """Format: APT-XXXXXX (6 hex chars from UUID)."""
    return f"APT-{uuid.uuid4().hex[:6].upper()}"


def _parse_date(s: str) -> date | None:
    s = (s or "").strip().lower()
    if not s or s == "next available":
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _time_str(h: int, m: int = 0) -> str:
    return f"{h:02d}:{m:02d}:00"


def _format_time(t: str) -> str:
    """Convert HH:MM:SS to natural '10:30 AM'."""
    try:
        parts = t.split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        if h == 0:
            return f"12:{m:02d} AM"
        if h < 12:
            return f"{h}:{m:02d} AM"
        if h == 12:
            return f"12:{m:02d} PM"
        return f"{h - 12}:{m:02d} PM"
    except (ValueError, IndexError):
        return t


def _format_date(d: date) -> str:
    """e.g. 'Wednesday January 15th' — speakable."""
    day = d.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{d.strftime('%A')} {d.strftime('%B')} {day}{suffix}"


def _next_weekdays(start: date, count: int) -> list[date]:
    days = []
    for i in range(14):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            days.append(d)
            if len(days) >= count:
                break
    return days


def _pick_spread_slots(slots: list[tuple[date, str]], max_slots: int = 3) -> list[tuple[date, str]]:
    """Pick slots spread across morning/midday/afternoon."""
    if len(slots) <= max_slots:
        return slots
    morning = [(d, t) for d, t in slots if t < "11:00:00"]
    midday = [(d, t) for d, t in slots if "11:00:00" <= t < "14:00:00"]
    afternoon = [(d, t) for d, t in slots if t >= "14:00:00"]
    picked = []
    for bucket in [morning, midday, afternoon]:
        if bucket and len(picked) < max_slots:
            picked.append(bucket[0])
    remaining = [s for s in slots if s not in picked]
    while len(picked) < max_slots and remaining:
        picked.append(remaining.pop(0))
    return sorted(picked, key=lambda x: (x[0], x[1]))


def _normalize_doctor_query(query: str) -> str:
    """Map vague or empty queries to a usable specialization so we don't return wrong doctor."""
    q = (query or "").strip().lower()
    if not q or q in ("doctor", "a doctor", "someone"):
        return "general"
    # Map common phrases to specialization for consistent routing
    if any(w in q for w in ("skin", "dermatolog", "rash", "acne")):
        return "dermatology"
    if any(w in q for w in ("heart", "cardio", "chest", "blood pressure")):
        return "cardiology"
    if any(w in q for w in ("child", "pediatric", "kid")):
        return "pediatrics"
    return query.strip() or "general"


async def check_availability(doctor_name_or_specialization: str, preferred_date: str = "next available") -> str:
    """
    Returns a SPEAKABLE sentence with 2-3 available slots.
    The LLM can relay this almost word-for-word. Never returns empty string.
    """
    db = await get_shared_db()
    query = _normalize_doctor_query(doctor_name_or_specialization)
    doctors = await db.get_doctors_by_name_or_specialization(query)

    # When the query matches multiple doctors (e.g. "Dr" matches all), prefer the one
    # whose name matches the query so we return that doctor's slots, not another's.
    if len(doctors) > 1:
        q = (query or "").lower().strip()
        by_name = [d for d in doctors if q in d.name.lower() or d.name.lower() in q]
        if by_name:
            doctors = by_name

    if not doctors:
        return "I don't have a doctor matching that. We have Dr. Chen for general practice, Dr. Okafor for cardiology, Dr. Rodriguez for dermatology, and Dr. Kim for pediatrics."

    today = date.today()
    if preferred_date and preferred_date.lower() != "next available":
        target = _parse_date(preferred_date)
        dates_to_check = [target] if target else _next_weekdays(today, 5)
    else:
        dates_to_check = _next_weekdays(today, 5)

    if not dates_to_check:
        return "I couldn't figure out which dates to check. Could you give me a specific date?"

    for doc in doctors:
        all_slots = []
        for d in dates_to_check:
            if d.strftime("%A") not in doc.available_days:
                continue

            existing = await db.get_appointments_by_doctor_and_date(doc.id, d.isoformat())
            booked_starts = {a.start_time for a in existing}

            t = datetime.combine(d, datetime.min.time().replace(hour=9))
            end_dt = datetime.combine(d, datetime.min.time().replace(hour=17))
            while t + timedelta(minutes=30) <= end_dt:
                start_s = _time_str(t.hour, t.minute)
                if start_s not in booked_starts:
                    all_slots.append((d, start_s))
                t += timedelta(minutes=30)

            if len(all_slots) >= 6:
                break

        picked = _pick_spread_slots(all_slots, max_slots=3)

        if picked:
            slot_parts = []
            for d, time_s in picked:
                slot_parts.append(f"{_format_date(d)} at {_format_time(time_s)}")

            if len(slot_parts) == 1:
                slots_text = slot_parts[0]
            elif len(slot_parts) == 2:
                slots_text = f"{slot_parts[0]} and {slot_parts[1]}"
            else:
                slots_text = f"{slot_parts[0]}, {slot_parts[1]}, and {slot_parts[2]}"

            return f"{doc.name} has openings on {slots_text}. Doctor ID is {doc.id}."

    doc_name = doctors[0].name
    return f"{doc_name} is fully booked for the dates I checked. Want me to check a different week or another doctor?"


async def book_appointment(doctor_id: int, patient_name: str, patient_phone: str, date: str, time: str, notes: str = "") -> str:
    """Returns a SPEAKABLE confirmation the LLM can relay directly."""
    db = await get_shared_db()

    if doctor_id <= 0:
        return "I need to know which doctor. Could you tell me the doctor's name or specialty?"

    doctor = await db.get_doctor_by_id(doctor_id)
    if not doctor:
        return "I couldn't find that doctor. Could you tell me which doctor you'd like?"

    if not patient_name.strip():
        return "I'll need your full name to book the appointment."

    if not patient_phone.strip():
        return "I'll need a phone number for the appointment."

    # Ensure date uses current year if a past year was sent (e.g. 2024)
    date_str = date.strip()
    try:
        parsed = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        today = date.today()
        if parsed.year < today.year:
            try:
                parsed = parsed.replace(year=today.year)
            except ValueError:
                # e.g. Feb 29 in non-leap year
                max_day = monthrange(today.year, parsed.month)[1]
                parsed = parsed.replace(year=today.year, day=min(parsed.day, max_day))
            date_str = parsed.isoformat()
    except (ValueError, IndexError):
        pass

    time = time.strip()
    if len(time) == 5:
        time += ":00"

    try:
        start_dt = datetime.strptime(time, "%H:%M:%S")
    except ValueError:
        return f"I couldn't understand the time {time}. Could you say it like 10:30?"

    end_dt = start_dt + timedelta(minutes=30)
    end_time = _time_str(end_dt.hour, end_dt.minute)

    existing = await db.get_appointments_by_doctor_and_date(doctor_id, date_str)
    for a in existing:
        if a.start_time == time:
            return "That slot was just taken. Let me check what else is available."

    apt_id = generate_appointment_id()
    await db.create_appointment(
        appointment_id=apt_id,
        doctor_id=doctor_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        date=date_str,
        start_time=time,
        end_time=end_time,
        notes=notes,
    )
    await db.upsert_caller(patient_phone, patient_name)
    await db.update_caller_preferences(patient_phone, "last_doctor", doctor.name)

    d = datetime.strptime(date_str, "%Y-%m-%d").date()

    return (
        f"All set! {patient_name} is booked with {doctor.name} "
        f"on {_format_date(d)} at {_format_time(time)}. "
        f"The appointment ID is {apt_id}."
    )


async def reschedule_appointment(appointment_id: str, new_date: str, new_time: str) -> str:
    """Returns a SPEAKABLE confirmation."""
    db = await get_shared_db()
    apt = await db.get_appointment_by_id(appointment_id)
    if not apt:
        return f"I couldn't find appointment {appointment_id}. Could you double-check that ID?"

    if len(new_time) == 5:
        new_time += ":00"

    try:
        end_dt = datetime.strptime(new_time, "%H:%M:%S") + timedelta(minutes=30)
    except ValueError:
        return f"I couldn't understand the time {new_time}. Could you say it like 2:30?"

    new_end = _time_str(end_dt.hour, end_dt.minute)

    existing = await db.get_appointments_by_doctor_and_date(apt.doctor_id, new_date)
    for a in existing:
        if a.id != appointment_id and a.start_time == new_time:
            return "That slot isn't available. Want me to check other times?"

    doctor = await db.get_doctor_by_id(apt.doctor_id)
    await db.reschedule_appointment(appointment_id, new_date, new_time, new_end)

    d = datetime.strptime(new_date, "%Y-%m-%d").date()
    doc_name = doctor.name if doctor else "Your doctor"

    return (
        f"Done! Your appointment with {doc_name} has been moved to "
        f"{_format_date(d)} at {_format_time(new_time)}."
    )


async def cancel_appointment(appointment_id: str, reason: str = "") -> str:
    """Returns a SPEAKABLE confirmation."""
    db = await get_shared_db()
    apt = await db.get_appointment_by_id(appointment_id)
    if not apt:
        return f"I couldn't find appointment {appointment_id}. Could you double-check that ID?"

    success = await db.update_appointment_status(appointment_id, "cancelled")
    if success:
        return f"Appointment {appointment_id} has been cancelled. If you need to rebook, just let me know."
    return f"I had trouble cancelling that. Let me transfer you to our front desk."


async def get_my_appointments(patient_phone: str, future_only: bool = True) -> str:
    """Returns a SPEAKABLE summary of the caller's appointments (by phone)."""
    db = await get_shared_db()
    if not (patient_phone or "").strip():
        return "I'll need your phone number to look up your appointments."

    appointments = await db.get_appointments_by_patient_phone(
        patient_phone.strip(), future_only=future_only
    )
    if not appointments:
        return "You don't have any upcoming appointments on file. Would you like to book one?"

    parts = []
    for apt in appointments:
        doctor = await db.get_doctor_by_id(apt.doctor_id)
        doc_name = doctor.name if doctor else "Your doctor"
        d = datetime.strptime(apt.appointment_date, "%Y-%m-%d").date()
        parts.append(
            f"{doc_name} on {_format_date(d)} at {_format_time(apt.start_time)} — {apt.id}"
        )
    if len(parts) == 1:
        return f"You have one appointment: {parts[0]}."
    return "You have " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."
