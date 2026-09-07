# Operations Runbook

This runbook captures the checks to make before and during a demo or hosted prototype session for Aria.

## Pre-run Checks

- Confirm `.env` contains current Deepgram, OpenAI, and Cartesia API keys.
- Run `uv sync` after dependency changes so the local environment matches `uv.lock`.
- Seed the demo database with `uv run python scripts/seed_db.py` when using a fresh checkout.
- Start the WebRTC bot with `uv run python -m agent.bot -t webrtc`.
- Open `http://127.0.0.1:7860/client` and verify the Call button connects.

## During a Session

- Watch the server log for STT, LLM, TTS, and transport errors.
- Track `[LATENCY] After STT` lines and note repeated turns above the target range.
- Confirm the bot escalates instead of answering medical advice, billing disputes, or complaint requests.
- Use test caller names and phone numbers only.

## After a Session

- Review `data/metrics.jsonl` for call outcomes and tool usage.
- Review `data/latency_log.jsonl` for p95 and p99 latency changes.
- Delete local demo data before sharing logs or screenshots.
- Record follow-up bugs with the exact phrase that triggered the issue.

## Recovery Notes

- If port 7860 is busy, stop the previous server or set `PORT=7861`.
- If audio connects but the bot stays silent, check STT and TTS API keys first.
- If appointment tools fail, reseed the local database and restart the bot.
