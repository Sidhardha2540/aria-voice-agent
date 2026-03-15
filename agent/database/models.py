"""
Pydantic models for Aria's database.
Validated, serializable, consistent — bad data is caught before reaching the LLM or caller.
"""
from enum import Enum

from pydantic import BaseModel, Field


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class Doctor(BaseModel):
    id: int
    name: str
    specialization: str
    available_days: list[str]
    slot_duration_minutes: int = 30


class Appointment(BaseModel):
    id: str
    doctor_id: int
    patient_name: str
    patient_phone: str
    appointment_date: str  # YYYY-MM-DD
    start_time: str
    end_time: str
    status: AppointmentStatus = AppointmentStatus.BOOKED
    created_at: str
    notes: str = ""


class Caller(BaseModel):
    id: int
    phone_number: str
    name: str = ""
    last_call_at: str
    preferences: dict = Field(default_factory=dict)
    call_count: int = 1


class ClinicInfo(BaseModel):
    key: str
    value: str
