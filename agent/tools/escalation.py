"""
Escalation tool — transfer to human staff.
In production this would trigger a SIP transfer; for demo we just announce it.
"""
import logging

logger = logging.getLogger("aria")


async def escalate_to_human(reason: str) -> str:
    """
    Escalate to human staff when the caller needs help beyond Aria's scope.

    Args:
        reason: Reason for the transfer (e.g. "billing question", "urgent medical").
    """
    logger.info("Escalation requested: %s", reason)
    return f"Transferring to front desk staff. Reason: {reason}. Please hold."
