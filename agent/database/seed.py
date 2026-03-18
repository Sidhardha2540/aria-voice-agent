"""
Seed the database with demo data for Aria.
Run once to populate doctors, sample appointments, and clinic FAQs.
"""
import asyncio
import random
from datetime import date, timedelta

from agent.database.db import get_shared_db
from agent.database.manager import db_manager
from agent.database.repositories import DoctorRepository


def _random_id() -> str:
    """Generate APT-XXXX style ID."""
    return f"APT-{random.randint(1000, 9999)}"


def _time_str(h: int, m: int = 0) -> str:
    """Format time as HH:MM:SS."""
    return f"{h:02d}:{m:02d}:00"


async def seed() -> None:
    """Populate the database with demo data."""
    db = await get_shared_db()
    doctor_repo = DoctorRepository(db_manager)

    # Check if already seeded
    doctors = await db.get_all_doctors()
    if doctors:
        print("Database already has data. Skipping seed.")
        return

    # 4 doctors
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for name, specialization in [
        ("Dr. Sarah Chen", "General Practice"),
        ("Dr. Michael Okafor", "Cardiology"),
        ("Dr. Emily Rodriguez", "Dermatology"),
        ("Dr. James Kim", "Pediatrics"),
    ]:
        await doctor_repo.add(name, specialization, weekdays, 30)
    print("Added 4 doctors.")

    # 5-6 sample appointments across next 2 weeks
    today = date.today()
    for _ in range(6):
        day_offset = random.randint(0, 14)
        d = today + timedelta(days=day_offset)
        if d.weekday() < 5:
            doctor_id = random.randint(1, 4)
            hour = random.choice([9, 10, 11, 14, 15])
            start = _time_str(hour)
            apt_id = _random_id()
            await db.create_appointment(
                appointment_id=apt_id,
                doctor_id=doctor_id,
                patient_name=f"Patient {random.randint(1, 10)}",
                patient_phone="555-0100",
                date=d.isoformat(),
                start_time=start,
                end_time=_time_str(hour, 30),
            )
    print("Added 6 sample appointments.")

    # Clinic info
    clinic_data = [
        ("hours", "We're open Monday through Friday, 8 AM to 6 PM, and Saturdays 9 AM to 1 PM."),
        ("address", "123 Medical Center Dr, Suite 200"),
        ("phone", "555-1234"),
        ("insurance", "We accept Blue Cross, Aetna, United Healthcare, Cigna, and Medicare."),
        ("services", "General practice, cardiology, dermatology, pediatrics, and preventive care."),
        ("parking", "Free parking available in the lot behind the building."),
        ("general", "Welcome to Greenfield Medical Center. We're here to help with your healthcare needs."),
        ("visit_instructions", "Please bring a valid ID and your insurance card. Arrive 15 minutes before your appointment. If your doctor requested fasting or other prep, follow those instructions — otherwise you can eat and drink as usual."),
    ]
    for key, val in clinic_data:
        await db.set_clinic_info(key, val)
    print(f"Added {len(clinic_data)} clinic info entries.")

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
