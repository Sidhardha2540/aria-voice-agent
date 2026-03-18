# Aria — Tools Reference

## Currently implemented tools

These are the tools the agent can call today. Schemas live in `agent/tools/registry.py`; handlers in `agent/tools/handlers.py`; backend logic in `agent/services/` and `agent/tools/`.

| Tool | Purpose | Backend |
|------|--------|---------|
| **check_availability** | Get available slots for a doctor by name or specialization (e.g. dermatology). Optional preferred date or "next available". | `appointments.check_availability()` |
| **book_appointment** | Book after confirming: doctor_id, patient_name, patient_phone, date, time; optional notes. | `appointments.book_appointment()` |
| **reschedule_appointment** | Move existing appointment (by APT-XXXX) to new date and time. | `appointments.reschedule_appointment()` |
| **cancel_appointment** | Cancel by appointment ID; optional reason. | `appointments.cancel_appointment()` |
| **get_clinic_info** | Clinic info by topic: hours, address, insurance, services, parking, visit_instructions, general. | `clinic_info.get_clinic_info()` |
| **list_doctors** | List doctors, optionally by specialization (e.g. dermatology). | `doctors.list_doctors()` |
| **get_my_appointments** | Caller's upcoming appointments by phone number. | `appointments.get_my_appointments()` |
| **request_medical_records** | Submit request for records (pickup or send); staff fulfill in ~5 days. | `medical_records.request_medical_records()` |
| **check_visit_instructions** | Pre-visit instructions (what to bring, fasting, arrive early). Optional doctor/specialty. | `clinic_info.get_visit_instructions()` |
| **send_confirmation_reminder** | Request SMS/email reminder for an appointment (~24h before). | `reminders.send_confirmation_reminder()` |
| **lookup_caller** | Check if phone number is a returning caller; personalize greeting. | `caller_memory.lookup_caller()` |
| **save_caller** | Save or update caller by phone and name. | `caller_memory.save_caller()` |
| **escalate_to_human** | Create transfer ticket (reason, caller name/phone, what they wanted, what Aria tried). | `escalation.escalate_to_human()` |
| **end_call** | End the call after a short sign-off when the caller is satisfied. | Inline in handlers (disconnect after 2s) |

**Total: 14 tools.**

---

## New tools you could add

Ideas for additional tools that fit a healthcare receptionist, ordered by effort and impact.

### 1. **list_doctors** (low effort)

- **What:** Return a short list of doctors (name, specialization) so the agent can say “We have Dr. Chen (dermatology), Dr. Rodriguez (cardiology)…”
- **Why:** Callers often ask “Who do you have?” or “Which doctors are there?” before choosing.
- **Implementation:** New schema in `registry.py`; handler calls existing `get_doctors_by_name_or_specialization("")` or a new `get_all_doctors()`-style API; optional filter by specialization.

### 2. **get_my_appointments** (low–medium effort)

- **What:** By phone number (and optionally name), return the caller’s upcoming (and maybe recent) appointments.
- **Why:** “What appointments do I have?” / “When is my next visit?”
- **Implementation:** New repo method or service: list appointments by `patient_phone` (and optionally filter by status/date). Return summary text (e.g. “You have one appointment: Dr. Chen, March 20 at 2:00 PM, APT-123456”).

### 3. **request_prescription_refill** (medium effort)

- **What:** Record a refill request (patient id or phone, medication name, pharmacy). No actual fulfillment; creates a ticket for staff.
- **Why:** Very common front-desk ask; agent can capture details and hand off.
- **Implementation:** New tool + table or JSON log (e.g. `data/refill_requests.jsonl` or DB table); handler writes record and returns “We’ve noted your refill request; someone will call you back.”

### 4. **request_medical_records** (medium effort)

- **What:** Request a copy of records (caller id, destination: email or pickup). Creates a ticket; no actual records sent by the bot.
- **Why:** “I need my records sent to my new doctor” / “Can I get a copy?”
- **Implementation:** New tool + storage (DB or file); handler creates request and returns confirmation and timeline (e.g. “Within 5 business days”).

### 5. **check_visit_instructions** (medium effort)

- **What:** By appointment ID or doctor + date, return pre-visit instructions (e.g. “fasting”, “bring ID”, “arrive 15 min early”). Data can be static per doctor or per appointment type.
- **Why:** “What do I need to do before my appointment?”
- **Implementation:** New clinic_info-style keys (e.g. `visit_instructions`) or a small table keyed by doctor/specialization; `get_clinic_info(topic="visit_instructions", doctor_id=…)` or dedicated tool.

### 6. **wait_time** (low–medium effort)

- **What:** Return current estimated wait (e.g. “About 15 minutes for walk-ins”) or “we don’t have walk-ins today.”
- **Why:** “How long is the wait?” / “Can I walk in?”
- **Implementation:** Static message from clinic info, or simple API that returns a string (could be updated by staff or a dashboard later).

### 7. **send_confirmation_reminder** (medium effort)

- **What:** Trigger an SMS or email reminder for an existing appointment (by APT-XXXX). Optional “resend” if they didn’t get it.
- **Why:** “Can you send me a reminder?” / “I never got the confirmation.”
- **Implementation:** Handler calls a small service that queues a message (e.g. Twilio/SendGrid stub or internal queue); or just record “reminder requested” and return “We’ll send a reminder 24 hours before.”

### 8. **pay_bill / get_balance** (medium–high effort)

- **What:** Get balance or last statement for a patient (by phone or MRN); optionally “pay” (record payment intent and hand off to billing).
- **Why:** “What do I owe?” / “I want to pay my bill.”
- **Implementation:** Needs billing data source (DB or API); pay could create a ticket or redirect to portal link. Privacy and compliance (PCI, HIPAA) must be considered.

### 4. **language_preference** (low effort)

- **What:** Set or read caller language preference (e.g. Spanish, Mandarin) for future calls or for staff.
- **Why:** “I prefer Spanish” / “Can someone call me back in Spanish?”
- **Implementation:** Store on caller record (e.g. `Caller.preferences["language"]`); optional: use to trigger human callback in that language or show in escalation ticket.

### 5. **symptom_checker_triage** (high effort, use carefully)

- **What:** Very simple triage: “For chest pain or difficulty breathing, please hang up and call 911. For other urgent issues, I can have a nurse call you back.”
- **Why:** Covers liability and directs emergencies away from the bot.
- **Implementation:** Mostly prompt + optional tool that records “urgent callback requested” and creates high-priority escalation; no actual medical advice.

---

## Summary

| Category | Current | Possible additions |
|----------|--------|--------------------|
| **Appointments** | check_availability, book, reschedule, cancel, get_my_appointments | — |
| **Doctors** | list_doctors | — |
| **Clinic info** | get_clinic_info, check_visit_instructions | wait_time |
| **Caller** | lookup_caller, save_caller | language_preference |
| **Handoff** | escalate_to_human, end_call | — |
| **Requests/tickets** | request_medical_records, send_confirmation_reminder | request_prescription_refill |
| **Billing** | — | get_balance, pay_bill (medium–high effort) |
| **Safety** | — | symptom_checker_triage (urgent / 911) |
