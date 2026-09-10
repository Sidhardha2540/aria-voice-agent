# Demo Script

Use this script to run a short, repeatable Aria demo without exposing real patient data.

## Setup

- Start from seeded demo data.
- Use a test caller name and a fictional phone number.
- Keep provider dashboards open only if they do not expose sensitive transcript data.
- Have `docs/TEST_CHECKLIST.md` nearby for deeper validation after the demo.

## Five-minute Flow

1. Start the WebRTC client and place a call.
2. Ask, "What are your hours today?"
3. Ask, "Do you have a dermatologist available this week?"
4. Book a sample appointment using a fictional name and phone number.
5. Ask, "Can you remind me before my appointment?"
6. Ask a question that should escalate, such as a medical advice request.
7. Say, "Thanks, that's all," and confirm the bot ends the call.

## What to Watch

- The greeting should feel immediate after the call connects.
- The bot should ask only for details needed to complete the current task.
- Appointment confirmation should include doctor, date, time, and caller identity.
- Escalation should be calm, brief, and clear about staff follow-up.
- The final sign-off should not continue the conversation.

## After the Demo

- Check latency logs for repeated slow turns.
- Check metrics logs for the completed flow and escalation.
- Remove any demo artifacts that include caller details.
