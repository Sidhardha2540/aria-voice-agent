# Aria bot — test checklist and tools

## Tools (functionalities) you can test

| Tool | What it does | How to test |
|------|----------------|-------------|
| **check_availability** | Get open slots for a doctor by name or specialty | "I need an appointment with a dermatologist" or "Dr. Rodriguez" → bot checks and offers 2–3 times. |
| **book_appointment** | Book after confirming details (uses tool params `appointment_date`, `start_time`) | Complete the booking flow: pick doctor → pick slot → give name → confirm → give phone → confirm → bot books and reads back ID. |
| **reschedule_appointment** | Move existing appointment to new date/time | "I need to reschedule my appointment" → give APT-XXXXXX → new date and time. |
| **cancel_appointment** | Cancel by appointment ID | "I want to cancel my appointment" → give APT-XXXXXX. |
| **get_clinic_info** | Hours, address, insurance, parking, services | "What are your hours?" / "Do you take insurance?" / "Where are you located?" / "Parking?" |
| **list_doctors** | Who's at the clinic (optionally by specialty) | "Who do you have?" / "Which doctors are there?" / "Do you have a dermatologist?" |
| **get_my_appointments** | Caller's upcoming appointments by phone | "What appointments do I have?" / "When is my next visit?" → give phone. |
| **request_medical_records** | Request a copy of records (pickup or send) | "I need my records sent" / "Can I get a copy of my records?" → confirm phone, name, email or pickup. |
| **check_visit_instructions** | What to do before the visit (bring ID, fasting, etc.) | "What do I need to do before my appointment?" / "Any instructions before I come in?" |
| **send_confirmation_reminder** | Request reminder for an appointment | "Can you send me a reminder?" / "I never got the confirmation" → give APT-XXXX. |
| **lookup_caller** | See if caller has called before (by phone) | Give your phone number or say "I've called before" → bot can personalize. |
| **save_caller** | Save/update caller name and phone | Done automatically after booking; or when you give name + phone. |
| **escalate_to_human** | Transfer to front desk (ticket created) | "I need to speak to someone" / "Billing question" / medical advice / complaint. |
| **end_call** | End the call when you're done and satisfied | Say "Thanks, that's all" / "Goodbye" / "Perfect, thank you" → bot says goodbye and disconnects after ~2 seconds. |

---

## Quick test flows

1. **FAQ** — "What are your hours?" / "Do you take Blue Cross?" → no tools or get_clinic_info.
2. **Book (full)** — "I need to see someone for a skin issue" → check_availability (dermatology) → pick slot → name → confirm → phone → confirm → book_appointment → end or "Thanks, bye" → end_call.
3. **Reschedule** — "I need to reschedule APT-123456 to next Tuesday at 2" → reschedule_appointment.
4. **Cancel** — "Cancel my appointment APT-123456" → cancel_appointment.
5. **Returning caller** — Give phone when asked → lookup_caller (bot can say "Welcome back, …").
6. **My appointments** — "What appointments do I have?" → give phone → get_my_appointments.
7. **List doctors** — "Who do you have?" or "Which dermatologists?" → list_doctors.
8. **Visit instructions** — "What should I do before my appointment?" → check_visit_instructions.
9. **Medical records** — "I need my records sent to my new doctor" → request_medical_records (phone, name, email/pickup).
10. **Reminder** — "Send me a reminder for APT-123456" → send_confirmation_reminder.
11. **Escalate** — "I need to talk to a person" or "Billing question" → escalate_to_human.
12. **Goodbye** — After any conclusion: "That's all, thanks" / "Goodbye" → end_call (bot disconnects).

---

## Latency (last run in metrics)

From **last run** in `data/metrics.jsonl` (session `5249dd1a`, 2026-03-16 23:02:45–23:05:19):

- **Average (after STT):** **2,620 ms** (~2.6 s per turn)
- **Per-turn range:** ~1,396 ms – 5,817 ms
- **Turns:** 12 | **Model:** gpt-4o-mini

Target is **200–300 ms** (natural gap). Current numbers are above that; check terminal for `[LATENCY] After STT:` and breakdown to see where time is spent (LLM TTFB, TTS, etc.).

---

## Disconnect on conclusion

When you're satisfied and say goodbye / thanks / "that's all", the bot should:

1. Give a short sign-off (e.g. "You're all set. Have a great day!").
2. Call **end_call**, which ends the call after ~2 seconds so the goodbye is spoken first.

If the call doesn’t end, say clearly "I'm done, thank you" or "Goodbye"; the bot is instructed to use end_call only when the conversation is naturally finished and you sound satisfied.
