"""Regression tests from REVIEW.md (booking bug, redaction, emotion plain text)."""
import asyncio
import inspect

import pytest

from agent.emotion_mapper import apply_emotion_transform
from agent.tools import appointments
from agent.utils.redact import redact_name, redact_phone


def test_book_appointment_uses_appointment_date_param_not_date():
    """date param must not shadow datetime.date (REVIEW 1.1)."""
    sig = inspect.signature(appointments.book_appointment)
    assert "appointment_date" in sig.parameters
    assert "date" not in sig.parameters


def test_apply_emotion_transform_does_not_inject_ssml_tags():
    last_e = ["content"]
    last_s = [1.05]
    text = "You're all set for Tuesday."
    out, em, sp = apply_emotion_transform(text, last_e, last_s)
    assert out == text
    assert "<emotion" not in out and "<speed" not in out


def test_redact_phone_masks_to_last_four():
    assert redact_phone("5551237890") == "***7890"


def test_redact_name_initials():
    assert redact_name("Jane Doe") == "JD."


def test_book_appointment_happy_path_uses_date_today(monkeypatch):
    """Ensure date.today() is the real class inside book_appointment (no shadowing)."""
    from datetime import date as date_cls
    from unittest.mock import AsyncMock, MagicMock

    async def fake_get_db():
        db = MagicMock()
        db.get_doctor_by_id = AsyncMock(
            return_value=MagicMock(id=1, name="Dr. Test", specialization="General Practice")
        )
        db.get_appointments_by_doctor_and_date = AsyncMock(return_value=[])

        async def create_apt(**kwargs):
            pass

        db.create_appointment = AsyncMock(side_effect=create_apt)
        db.upsert_caller = AsyncMock()
        db.update_caller_preferences = AsyncMock(return_value=True)
        return db

    monkeypatch.setattr(appointments, "get_shared_db", fake_get_db)

    async def _run():
        y = date_cls.today().year
        appt_date = f"{y}-06-15"
        return await appointments.book_appointment(
            doctor_id=1,
            patient_name="Test Patient",
            patient_phone="555-0000",
            appointment_date=appt_date,
            start_time="10:00",
            notes="",
        )

    result = asyncio.run(_run())
    assert "booked" in result.lower() or "All set" in result
    assert "APT-" in result
