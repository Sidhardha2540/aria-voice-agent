"""
Tool handlers — the bridge between Pipecat's function calling and our services.
Every handler is wrapped in safe_tool_call so exceptions become spoken errors.

Handlers receive raw LLM arguments: use safe_int/safe_str for all inputs.
"""
from agent.core.errors import safe_int, safe_str, safe_tool_call
from agent.services import appointments, caller_memory, clinic_info, escalation


def create_tool_handlers(
    session_id: str = "unknown",
    metrics_ref: dict | None = None,
):
    """
    Factory that creates tool handlers bound to a session.
    Each handler is wrapped in safe_tool_call.
    metrics_ref: optional dict with "metrics" key for recording tool calls, caller_recognized, escalation.

    Returns a dict of {tool_name: async handler} for llm.register_function().
    """

    async def _check_availability(params):
        async def _inner(p):
            args = p.arguments
            result = await appointments.check_availability(
                safe_str(args.get("doctor_name_or_specialization"), ""),
                safe_str(args.get("preferred_date"), "next available"),
            )
            await p.result_callback(result)
        await safe_tool_call("check_availability", _inner, params, session_id)

    async def _book_appointment(params):
        async def _inner(p):
            args = p.arguments
            result = await appointments.book_appointment(
                doctor_id=safe_int(args.get("doctor_id"), 0),
                patient_name=safe_str(args.get("patient_name"), ""),
                patient_phone=safe_str(args.get("patient_phone"), ""),
                date=safe_str(args.get("date"), ""),
                time=safe_str(args.get("time"), ""),
                notes=safe_str(args.get("notes"), ""),
            )
            await p.result_callback(result)
        await safe_tool_call("book_appointment", _inner, params, session_id)

    async def _reschedule_appointment(params):
        async def _inner(p):
            args = p.arguments
            result = await appointments.reschedule_appointment(
                safe_str(args.get("appointment_id"), ""),
                safe_str(args.get("new_date"), ""),
                safe_str(args.get("new_time"), ""),
            )
            await p.result_callback(result)
        await safe_tool_call("reschedule_appointment", _inner, params, session_id)

    async def _cancel_appointment(params):
        async def _inner(p):
            args = p.arguments
            result = await appointments.cancel_appointment(
                safe_str(args.get("appointment_id"), ""),
                safe_str(args.get("reason"), ""),
            )
            await p.result_callback(result)
        await safe_tool_call("cancel_appointment", _inner, params, session_id)

    async def _get_clinic_info(params):
        async def _inner(p):
            result = await clinic_info.get_clinic_info(
                safe_str(p.arguments.get("topic"), "general"),
            )
            await p.result_callback(result)
        await safe_tool_call("get_clinic_info", _inner, params, session_id)

    async def _lookup_caller(params):
        async def _inner(p):
            result = await caller_memory.lookup_caller(
                safe_str(p.arguments.get("phone_number"), ""),
            )
            if metrics_ref:
                m = metrics_ref.get("metrics")
                if m and "Returning caller" in str(result):
                    m.set_caller_recognized(True)
            await p.result_callback(result)
        await safe_tool_call("lookup_caller", _inner, params, session_id)

    async def _save_caller(params):
        async def _inner(p):
            args = p.arguments
            result = await caller_memory.save_caller(
                safe_str(args.get("phone_number"), ""),
                safe_str(args.get("name"), ""),
            )
            await p.result_callback(result)
        await safe_tool_call("save_caller", _inner, params, session_id)

    async def _escalate_to_human(params):
        async def _inner(p):
            args = p.arguments
            reason = safe_str(args.get("reason"), "")
            result = await escalation.escalate_to_human(
                reason=reason,
                caller_name=safe_str(args.get("caller_name"), ""),
                caller_phone=safe_str(args.get("caller_phone"), ""),
                caller_wanted=safe_str(args.get("caller_wanted"), ""),
                aria_tried=safe_str(args.get("aria_tried"), ""),
            )
            if metrics_ref:
                m = metrics_ref.get("metrics")
                if m:
                    m.record_escalation(reason)
            await p.result_callback(result)
        await safe_tool_call("escalate_to_human", _inner, params, session_id)

    return {
        "check_availability": _check_availability,
        "book_appointment": _book_appointment,
        "reschedule_appointment": _reschedule_appointment,
        "cancel_appointment": _cancel_appointment,
        "get_clinic_info": _get_clinic_info,
        "lookup_caller": _lookup_caller,
        "save_caller": _save_caller,
        "escalate_to_human": _escalate_to_human,
    }
