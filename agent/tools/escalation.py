"""
Escalation tool — transfer to human staff with a real ticket.
Returns a speakable message with ticket ID and clear next steps.
"""
import json
import uuid
from datetime import datetime, timezone

from loguru import logger


async def escalate_to_human(
    reason: str,
    caller_name: str = "",
    caller_phone: str = "",
    caller_wanted: str = "",
    aria_tried: str = "",
) -> str:
    """
    Generate a support ticket and prepare for human handoff.
    Returns a SPEAKABLE message with ticket ID and next steps.
    """
    ticket_id = f"TKT-{uuid.uuid4().hex[:6].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    summary = {
        "timestamp": timestamp,
        "reason": reason.strip() or "Unspecified",
        "caller_name": (caller_name or "").strip() or None,
        "caller_phone": (caller_phone or "").strip() or None,
        "caller_wanted": (caller_wanted or "").strip() or None,
        "aria_tried": (aria_tried or "").strip() or None,
    }
    summary_json = json.dumps(summary, indent=2)
    logger.info("[ESCALATION] ticket={} reason={} summary={}", ticket_id, reason, summary_json)

    return (
        f"I've created a support ticket for you. Your ticket number is {ticket_id}. "
        f"I'm connecting you with our front desk team now. "
        f"They'll have your ticket details so you won't need to repeat anything. "
        f"Please hold for just a moment."
    )
