"""List doctors — for 'who do you have?' / 'which doctors?'."""
from agent.database.db import get_shared_db


async def list_doctors(specialization_filter: str = "") -> str:
    """
    Return a speakable list of doctors. Optional filter by specialization
    (e.g. dermatology, cardiology). Empty string = all doctors.
    """
    db = await get_shared_db()
    if (specialization_filter or "").strip():
        doctors = await db.get_doctors_by_name_or_specialization(
            specialization_filter.strip()
        )
    else:
        doctors = await db.get_all_doctors()

    if not doctors:
        return "I don't have any doctors matching that. We have general practice, cardiology, dermatology, and pediatrics — would you like to hear who's available in one of those?"

    if len(doctors) == 1:
        d = doctors[0]
        return f"We have {d.name}, specializing in {d.specialization}."
    parts = [f"{d.name} ({d.specialization})" for d in doctors]
    if len(parts) == 2:
        return f"Our doctors are {parts[0]} and {parts[1]}."
    return "Our doctors are " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."
