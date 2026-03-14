"""
Seed the database with demo data for Aria.
Run once to populate doctors, sample appointments, and clinic FAQs.
"""
import asyncio
import json
import random
from datetime import date, timedelta

from agent.config import DB_PATH
from agent.database.db import AsyncDatabase


def _random_id() -> str:
    """Generate APT-XXXX style ID."""
    return f"APT-{random.randint(1000, 9999)}"


def _time_str(h: int, m: int = 0) -> str:
    """Format time as HH:MM:SS."""
    return f"{h:02d}:{m:02d}:00"


async def seed() -> None:
    """Populate the database with demo data."""
    db = AsyncDatabase(DB_PATH)
    await db.connect()

    # Check if already seeded
    doctors = await db.get_all_doctors()
    if doctors:
        print("Database already has data. Skipping seed.")
        await db.close()
        return

    # 4 doctors
    weekdays = json.dumps(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    await db._conn.executemany(
        """INSERT INTO doctors (name, specialization, available_days, slot_duration_minutes)
           VALUES (?, ?, ?, 30)""",
        [
            ("Dr. Sarah Chen", "General", weekdays),
            ("Dr. Michael Okafor", "Cardiology", weekdays),
            ("Dr. Emily Rodriguez", "Dermatology", weekdays),
            ("Dr. James Kim", "Pediatrics", weekdays),
        ],
    )
    await db._conn.commit()
    print("Added 4 doctors.")

    # 5-6 sample appointments across next 2 weeks
    today = date.today()
    appointments = []
    for _ in range(6):
        day_offset = random.randint(0, 14)
        d = today + timedelta(days=day_offset)
        if d.weekday() < 5:  # weekday
            doctor_id = random.randint(1, 4)
            hour = random.choice([9, 10, 11, 14, 15])
            start = _time_str(hour)
            end = _time_str(hour, 30)
            apt_id = _random_id()
            while any(a[0] == apt_id for a in appointments):
                apt_id = _random_id()
            created = f"{d.isoformat()}T09:00:00Z"
            appointments.append(
                (apt_id, doctor_id, f"Patient {random.randint(1, 10)}", "555-0100", d.isoformat(), start, end, "booked", created, "")
            )

    for apt_id, doctor_id, patient_name, phone, dt, start, end, _, _, _ in appointments:
        await db.create_appointment(
            appointment_id=apt_id,
            doctor_id=doctor_id,
            patient_name=patient_name,
            patient_phone=phone,
            date=dt,
            start_time=start,
            end_time=end,
        )
    print(f"Added {len(appointments)} sample appointments.")

    # Clinic info
    clinic_data = [
        ("hours", "We're open Monday through Friday, 8 AM to 6 PM, and Saturdays 9 AM to 1 PM."),
        ("address", "123 Medical Center Dr, Suite 200"),
        ("phone", "555-1234"),
        ("insurance", "We accept Blue Cross, Aetna, United Healthcare, Cigna, and Medicare."),
        ("services", "General practice, cardiology, dermatology, pediatrics, and preventive care."),
        ("parking", "Free parking available in the lot behind the building."),
        ("general", "Welcome to Greenfield Medical Center. We're here to help with your healthcare needs."),
    ]
    for key, val in clinic_data:
        await db.set_clinic_info(key, val)
    print(f"Added {len(clinic_data)} clinic info entries.")

    await db.close()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
