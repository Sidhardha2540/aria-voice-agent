"""
Clinic info tool — FAQs, hours, address, insurance, services.
"""
from agent.database.db import get_shared_db


# Map common topics to DB keys
TOPIC_MAP = {
    "hours": "hours",
    "time": "hours",
    "open": "hours",
    "when": "hours",
    "address": "address",
    "location": "address",
    "where": "address",
    "directions": "address",
    "insurance": "insurance",
    "services": "services",
    "parking": "parking",
    "general": "general",
    "hello": "general",
    "hi": "general",
    "visit_instructions": "visit_instructions",
    "instructions": "visit_instructions",
    "before_visit": "visit_instructions",
    "prepare": "visit_instructions",
}


async def get_clinic_info(topic: str) -> str:
    """
    Get clinic information by topic.

    Args:
        topic: One of: hours, address, insurance, services, parking, visit_instructions, general.
    """
    db = await get_shared_db()
    t = (topic or "").strip().lower()
    key = TOPIC_MAP.get(t, t) if t else "general"
    val = await db.get_clinic_info(key)
    if val:
        return val
    return "I don't have specific info on that, but our front desk can definitely help."


async def get_visit_instructions(doctor_name_or_specialization: str = "") -> str:
    """
    Get pre-visit instructions (what to bring, fasting, etc.).
    Optional: filter by doctor or specialization for specialty-specific instructions.
    """
    db = await get_shared_db()
    spec = (doctor_name_or_specialization or "").strip().lower()
    if spec:
        # Try specialty-specific key first (e.g. visit_instructions_dermatology)
        for suffix in ("dermatology", "cardiology", "pediatrics", "general practice"):
            if suffix in spec or spec in suffix:
                key = f"visit_instructions_{suffix.replace(' ', '_')}"
                val = await db.get_clinic_info(key)
                if val:
                    return val
                break
    val = await db.get_clinic_info("visit_instructions")
    if val:
        return val
    return (
        "Generally, please bring your ID and insurance card, and arrive about 15 minutes early. "
        "If your doctor asked you to fast or do anything special, follow those instructions. "
        "For procedure-specific instructions, our front desk can confirm when you arrive."
    )
