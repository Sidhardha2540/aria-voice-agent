# Test Triage Notes

Use these notes when an automated test, manual voice flow, or provider check fails.

## First Checks

- Confirm the local environment was installed after the latest pull.
- Check that `.env` exists and contains placeholder-free values for required provider keys.
- Re-run the exact command once to separate flaky provider behavior from deterministic failures.
- Capture the full command, branch name, and timestamp in the issue or follow-up note.

## Voice Session Failures

- If the browser cannot connect, check the server port and WebRTC startup logs.
- If speech is transcribed but no answer plays, inspect LLM and TTS provider responses.
- If the agent interrupts too quickly, review VAD and endpointing settings.
- If the final goodbye does not end the call, test the end-call tool path directly.

## Tool Flow Failures

- For appointment booking issues, reseed the database and retry with a known doctor and slot.
- For caller lookup issues, verify phone number normalization before checking persistence.
- For escalation issues, confirm the prompt classifies medical advice and complaints as handoff cases.
- For reminders or records requests, check that the response promises staff follow-up instead of direct fulfillment.

## Reporting

- Include the caller phrase that triggered the failure.
- Note whether the failure was reproduced by tests, manual browser calling, or both.
- Attach sanitized log excerpts only after removing names, phone numbers, and appointment details.
