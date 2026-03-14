"""
Escalation tool — transfer to human staff.
In production this would trigger a SIP transfer; for demo we log the handoff summary.
"""
import json
from datetime import datetime

from loguru import logger

WARM_HANDOFF_MESSAGE = (
    "I want to make sure you get the right help. Let me connect you with our front desk team. "
    "I'll pass along what we've discussed so you won't have to repeat yourself."
)


async def escalate_to_human(
    reason: str,
    caller_name: str = "",
    caller_phone: str = "",
    caller_wanted: str = "",
    aria_tried: str = "",
) -> str:
    """
    Escalate to human staff when the caller needs help beyond Aria's scope.

    Args:
        reason: Why escalation was triggered (e.g. "billing question", "user frustrated").
        caller_name: Caller's name if known.
        caller_phone: Caller's phone if known.
        caller_wanted: What the caller asked for / wanted.
        aria_tried: What Aria already attempted (tools called, outcomes).
    """
    summary = {
        "timestamp": datetime.now().isoformat(),
        "reason": reason.strip() or "Unspecified",
        "caller_name": (caller_name or "").strip() or None,
        "caller_phone": (caller_phone or "").strip() or None,
        "caller_wanted": (caller_wanted or "").strip() or None,
        "aria_tried": (aria_tried or "").strip() or None,
    }
    summary_json = json.dumps(summary, indent=2)
    logger.info("[ESCALATION] Reason: %s, Summary: %s", reason, summary_json)
    return WARM_HANDOFF_MESSAGE
