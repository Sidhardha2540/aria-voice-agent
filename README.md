# aria-voice-agent

Production-grade voice AI agent with sub-300ms latency. Pipecat + Deepgram + Groq + Cartesia.

## Setup

1. Copy `.env.example` to `.env` and set `DEEPGRAM_API_KEY`, `GROQ_API_KEY`, `CARTESIA_API_KEY`.
2. `uv sync` (or `pip install -e .`).
3. Seed the DB: `uv run python scripts/seed_db.py`.
4. Run: `uv run python -m agent.bot -t webrtc` (or `uv run python -m agent.main -t webrtc`).

## Project structure

- **agent/config.py** — Pydantic settings (validated at startup).
- **agent/core/** — Pipeline builder, session, context manager, error boundaries.
- **agent/transport/** — Transport factory (WebRTC, Twilio, Daily).
- **agent/database/** — Single connection manager, repositories, Pydantic models.
- **agent/tools/** — Tool schemas and handlers (with safe_tool_call).
- **agent/observability/** — Health check and logging.

See `docs/ROADMAP.md` for the full implementation guide.
