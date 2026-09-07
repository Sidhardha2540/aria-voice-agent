# Privacy Review Guide

Aria is a prototype for a healthcare receptionist workflow. Use this guide to keep privacy risks visible during demos and development.

## Data Boundaries

- Use synthetic caller names, phone numbers, appointment notes, and clinic records.
- Do not paste real patient information into prompts, tickets, logs, screenshots, or seed data.
- Treat `data/metrics.jsonl`, `data/feedback.jsonl`, and `data/latency_log.jsonl` as potentially sensitive during testing.
- Delete local demo data before publishing screenshots or sharing an archive.

## Conversation Handling

- Route medical advice, emergencies, billing disputes, and complaints to human escalation.
- Keep appointment scheduling responses limited to operational details the tool result provides.
- Avoid repeating full phone numbers unless the caller needs to confirm them.
- Prefer short confirmations that do not expose unnecessary caller details.

## Logging Review

- Check logs for raw transcripts before sharing them outside the development machine.
- Confirm new tool handlers avoid logging request payloads with caller identifiers.
- Redact provider errors if they echo request content.
- Keep latency metrics useful without storing more conversation text than necessary.

## Production Gap Notes

- This prototype is not HIPAA-compliant.
- Production use would need authentication, audit controls, encryption policies, retention rules, and vendor agreements.
- Staff handoff workflows should be reviewed with clinic operators before live deployment.
