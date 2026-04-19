# Changelog

All notable changes to this project are documented here.

## Unreleased

- Ongoing improvements to tools, latency tracking, and documentation.
- Cross-links between ARCHITECTURE, TOOLS, and diagnostics docs.
- **Production readiness:** Fixed `book_appointment` `date`/`datetime.date` shadowing bug; `appointment_date` + `start_time` tool params; UTC timestamps via `utc_now_iso_z()`; partial unique index on booked slots; batched availability DB reads; persona-first system prompt; barge-in acknowledgement injection before TTS; Cartesia emotion SSML removed from streamed text (plain text only); duplicate `atexit` DB shutdown removed from `bot.py`; `asyncio.get_running_loop()` in metrics/intent router; metrics write task error logging; PII-redacted escalation and JSONL logs; README **Status**; docker-compose Postgres credentials from env; internal docs moved to `docs/internal/`.
