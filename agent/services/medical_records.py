"""Medical records request — log request for staff to fulfill."""
import json
from datetime import datetime
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_REQUESTS_FILE = _DATA_DIR / "medical_record_requests.jsonl"


async def request_medical_records(
    caller_phone: str,
    caller_name: str = "",
    destination: str = "pickup",
    notes: str = "",
) -> str:
    """
    Record a medical records request. destination: 'email', 'pickup', or description.
    Returns a speakable confirmation. Staff fulfill separately.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "requested_at": datetime.utcnow().isoformat() + "Z",
        "caller_phone": (caller_phone or "").strip(),
        "caller_name": (caller_name or "").strip(),
        "destination": (destination or "pickup").strip().lower(),
        "notes": (notes or "").strip()[:500],
    }
    with open(_REQUESTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if "email" in record["destination"]:
        return (
            "I've submitted your medical records request. "
            "Our staff will send the records to the email or address you provided within 5 business days. "
            "If you don't receive them, call back and we can resend."
        )
    return (
        "I've submitted your medical records request. "
        "You can pick up a copy at the front desk within 5 business days, or we can send them to you — "
        "just let us know your preferred method. Is there anything else?"
    )
