"""Function-calling tools for Aria — appointments, clinic info, caller memory, escalation."""
from agent.tools.appointments import (
    check_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
)
from agent.tools.clinic_info import get_clinic_info
from agent.tools.caller_memory import lookup_caller
from agent.tools.escalation import escalate_to_human

__all__ = [
    "check_availability",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "get_clinic_info",
    "lookup_caller",
    "escalate_to_human",
]
