"""Appointment reminder requests — log so staff can send SMS/email."""
import json
from datetime import datetime
from pathlib import Path

from agent.database.db import get_shared_db

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_REQUESTS_FILE = _DATA_DIR / "reminder_requests.jsonl"


async def send_confirmation_reminder(appointment_id: str, patient_phone: str = "") -> str:
    """
    Request a confirmation/reminder for an existing appointment.
    Validates the appointment exists; logs the request for staff to send SMS/email.
    """
    db = await get_shared_db()
    apt = await db.get_appointment_by_id((appointment_id or "").strip())
    if not apt:
        return (
            f"I couldn't find an appointment with ID {appointment_id}. "
            "Please check the confirmation we sent you, or I can look up your appointments by phone."
        )
    if apt.status != "booked":
        return f"That appointment is no longer active, so we won't send a reminder. Would you like to rebook?"

    phone = (patient_phone or apt.patient_phone or "").strip()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "requested_at": datetime.utcnow().isoformat() + "Z",
        "appointment_id": apt.id,
        "patient_phone": phone,
        "patient_name": apt.patient_name or "",
    }
    with open(_REQUESTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return (
        "I've requested a reminder for that appointment. "
        "You'll get a text or email about 24 hours before your visit. "
        "Is there anything else?"
    )
