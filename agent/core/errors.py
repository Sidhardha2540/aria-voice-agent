"""
Error boundaries for the voice pipeline.
Rule: No unhandled exception should ever reach the pipeline.
Every failure becomes a spoken response to the caller.
"""
import asyncio
import traceback
from enum import Enum

from loguru import logger

# Max time per tool call — hung DB/API = spoken error, not frozen call (DIAGNOSIS R6)
TOOL_CALL_TIMEOUT_SECONDS = 8.0


class ErrorSeverity(Enum):
    """How bad is this failure?"""
    RECOVERABLE = "recoverable"   # Tool failed, but call continues
    DEGRADED = "degraded"        # Feature unavailable, offer alternative
    CRITICAL = "critical"        # Must escalate to human


# Spoken error messages — these are what the CALLER hears
TOOL_ERROR_RESPONSES = {
    "check_availability": "I'm having trouble checking the schedule right now. Let me transfer you to our front desk so they can help.",
    "book_appointment": "I ran into an issue while booking that. Let me connect you with our staff to make sure it's done correctly.",
    "reschedule_appointment": "I'm having trouble rescheduling. Let me transfer you to make sure your appointment is handled properly.",
    "cancel_appointment": "I couldn't process that cancellation. Let me connect you with someone who can help.",
    "get_clinic_info": "I'm having a little trouble looking that up. Is there something else I can help with, or would you like me to transfer you?",
    "lookup_caller": "I wasn't able to pull up your records, but no worries, I can still help you.",
    "save_caller": "I had a small issue saving that. I can still help you with your appointment.",
    "escalate_to_human": "I'm connecting you with our staff right now. Please hold for just a moment.",
    "default": "I ran into a small issue. Let me connect you with our front desk to make sure you're taken care of.",
}


async def safe_tool_call(tool_name: str, handler, params, session_id: str = "unknown"):
    """
    Wraps every tool execution with timeout and error handling.

    On success: handler runs and calls params.result_callback(result).
    On timeout or exception: logs, then calls params.result_callback with a caller-friendly spoken message.
    """
    try:
        await asyncio.wait_for(handler(params), timeout=TOOL_CALL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error("Tool '{tool}' timed out after {timeout}s | session={session}", tool=tool_name, timeout=TOOL_CALL_TIMEOUT_SECONDS, session=session_id)
        msg = "I'm having trouble looking that up right now. Let me transfer you to our front desk."
        await params.result_callback(msg)
    except Exception as e:
        logger.error(
            "Tool '{tool}' failed | session={session} | error={error} | traceback={tb}",
            tool=tool_name,
            session=session_id,
            error=str(e),
            tb=traceback.format_exc(),
        )
        msg = TOOL_ERROR_RESPONSES.get(tool_name, TOOL_ERROR_RESPONSES["default"])
        await params.result_callback(msg)


def safe_int(value, default: int = 0) -> int:
    """Safely convert LLM output to int. LLMs sometimes send '2' or 'two' or 2."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip().lower()
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return int(float(value))
        except ValueError:
            pass
        word_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        if value in word_map:
            return word_map[value]
    return default


def safe_str(value, default: str = "") -> str:
    """Safely extract a string from LLM output."""
    if value is None:
        return default
    return str(value).strip()
