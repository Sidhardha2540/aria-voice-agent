"""
Tool schema definitions — used by the pipeline for LLM function calling.
"""
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema


def get_tool_schemas() -> ToolsSchema:
    """Returns all tool schemas. Defined once, used everywhere."""
    return ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_availability",
            description="Check available appointment slots for a doctor by name or specialization. ALWAYS call this before suggesting times.",
            properties={
                "doctor_name_or_specialization": {
                    "type": "string",
                    "description": "Doctor name (e.g. 'Dr. Chen') or specialization (e.g. 'dermatology')",
                },
                "preferred_date": {
                    "type": "string",
                    "description": "Date as YYYY-MM-DD or 'next available'. Default: 'next available'",
                },
            },
            required=["doctor_name_or_specialization"],
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book an appointment. ALWAYS confirm all details with the caller before calling this.",
            properties={
                "doctor_id": {"type": "integer", "description": "Doctor ID from check_availability results"},
                "patient_name": {"type": "string", "description": "Patient's full name as stated by caller"},
                "patient_phone": {"type": "string", "description": "Patient's phone number"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Time as HH:MM (24h format)"},
                "notes": {"type": "string", "description": "Reason for visit or other notes"},
            },
            required=["doctor_id", "patient_name", "patient_phone", "date", "time"],
        ),
        FunctionSchema(
            name="reschedule_appointment",
            description="Reschedule an existing appointment to a new date/time.",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (format: APT-XXXX)"},
                "new_date": {"type": "string", "description": "New date as YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "New time as HH:MM (24h format)"},
            },
            required=["appointment_id", "new_date", "new_time"],
        ),
        FunctionSchema(
            name="cancel_appointment",
            description="Cancel an existing appointment.",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (format: APT-XXXX)"},
                "reason": {"type": "string", "description": "Reason for cancellation (optional)"},
            },
            required=["appointment_id"],
        ),
        FunctionSchema(
            name="get_clinic_info",
            description="Get clinic information: hours, address, insurance accepted, services offered, parking details.",
            properties={
                "topic": {
                    "type": "string",
                    "description": "One of: hours, address, insurance, services, parking, visit_instructions, general",
                },
            },
            required=["topic"],
        ),
        FunctionSchema(
            name="list_doctors",
            description="List doctors at the clinic, optionally by specialization (e.g. dermatology, cardiology). Use when caller asks who we have or which doctors are available.",
            properties={
                "specialization_filter": {
                    "type": "string",
                    "description": "Optional: filter by specialization (e.g. 'dermatology'). Leave empty for all doctors.",
                },
            },
            required=[],
        ),
        FunctionSchema(
            name="get_my_appointments",
            description="Look up the caller's upcoming appointments by their phone number. Use when they ask what appointments they have or when their next visit is.",
            properties={
                "patient_phone": {"type": "string", "description": "Caller's phone number"},
                "future_only": {
                    "type": "boolean",
                    "description": "If true, only return future appointments. Default true.",
                },
            },
            required=["patient_phone"],
        ),
        FunctionSchema(
            name="request_medical_records",
            description="Submit a request for the caller's medical records (copy to pick up or send). Staff will fulfill within 5 business days. Use when caller wants their records sent or a copy.",
            properties={
                "caller_phone": {"type": "string", "description": "Caller's phone number"},
                "caller_name": {"type": "string", "description": "Caller's name if known"},
                "destination": {
                    "type": "string",
                    "description": "One of: email, pickup, or brief description of where to send",
                },
                "notes": {"type": "string", "description": "Optional notes (e.g. email address)"},
            },
            required=["caller_phone"],
        ),
        FunctionSchema(
            name="check_visit_instructions",
            description="Get pre-visit instructions: what to bring, whether to fast, arrive early, etc. Optional filter by doctor or specialty for specific instructions.",
            properties={
                "doctor_name_or_specialization": {
                    "type": "string",
                    "description": "Optional: doctor name or specialty (e.g. dermatology) for specialty-specific instructions",
                },
            },
            required=[],
        ),
        FunctionSchema(
            name="send_confirmation_reminder",
            description="Request that a confirmation or reminder be sent for an existing appointment (SMS/email ~24h before). Use when caller says they didn't get a reminder or wants one sent.",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (e.g. APT-XXXXXX)"},
                "patient_phone": {"type": "string", "description": "Optional: caller's phone if different from booking"},
            },
            required=["appointment_id"],
        ),
        FunctionSchema(
            name="lookup_caller",
            description="Look up if a caller has called before by their phone number. Use to personalize the conversation.",
            properties={
                "phone_number": {"type": "string", "description": "Caller's phone number"},
            },
            required=["phone_number"],
        ),
        FunctionSchema(
            name="save_caller",
            description="Save or update caller record when new caller gives name and phone.",
            properties={
                "phone_number": {"type": "string", "description": "Phone number"},
                "name": {"type": "string", "description": "Caller name"},
            },
            required=["phone_number"],
        ),
        FunctionSchema(
            name="escalate_to_human",
            description="Transfer the call to human front desk staff. Use ONLY when: medical advice requested, billing questions, caller explicitly asks to speak to a person, or complaint. Do NOT use when the caller is only correcting their name spelling or giving a small booking correction — continue the booking instead.",
            properties={
                "reason": {"type": "string", "description": "Brief reason for the transfer"},
                "caller_name": {"type": "string", "description": "Caller name if known"},
                "caller_phone": {"type": "string", "description": "Caller phone if known"},
                "caller_wanted": {"type": "string", "description": "What the caller asked for"},
                "aria_tried": {"type": "string", "description": "What Aria already attempted"},
            },
            required=["reason"],
        ),
        FunctionSchema(
            name="end_call",
            description="End the call when the conversation is naturally finished and the caller is satisfied (said thanks, goodbye, that's all, or sounds done). Use after a brief sign-off. Do NOT use when escalating or when the caller might have more to ask.",
            properties={},
            required=[],
        ),
    ])
