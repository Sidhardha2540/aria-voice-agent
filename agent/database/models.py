"""
Data models (dataclasses) for Aria's database.
These represent the shape of data in our SQLite tables.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Doctor:
    """A doctor at the clinic."""
    id: int
    name: str
    specialization: str
    available_days: list[str]  # e.g. ["Monday", "Tuesday", ...]
    slot_duration_minutes: int = 30


@dataclass
class Appointment:
    """An appointment record."""
    id: str
    doctor_id: int
    patient_name: str
    patient_phone: str
    appointment_date: str  # ISO date "YYYY-MM-DD"
    start_time: str       # ISO time "HH:MM:SS"
    end_time: str
    status: str           # "booked" | "cancelled" | "completed"
    created_at: str
    notes: str = ""


@dataclass
class Caller:
    """A caller (patient) we've spoken to before."""
    id: int
    phone_number: str
    name: str
    last_call_at: str
    preferences: dict  # JSON blob
    call_count: int


@dataclass
class ClinicInfo:
    """Key-value store for FAQs, hours, etc."""
    key: str
    value: str
