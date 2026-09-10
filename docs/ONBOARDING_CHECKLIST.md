# Onboarding Checklist

Use this checklist when setting up Aria on a new machine or handing the project to another contributor.

## Local Setup

- Install Python 3.11 or newer.
- Install `uv` or prepare a virtual environment for `pip install -e .`.
- Clone the repository and run `uv sync`.
- Copy `.env.example` to `.env` before starting the bot.
- Add development API keys for Deepgram, OpenAI, and Cartesia.

## First Run

- Seed local data with `uv run python scripts/seed_db.py`.
- Start the WebRTC bot with `uv run python -m agent.bot -t webrtc`.
- Open `http://127.0.0.1:7860/client`.
- Place one test call and confirm the greeting plays.
- Ask for clinic hours to verify the FAQ path.

## Contributor Context

- Read `README.md` for the main project overview.
- Read `ARCHITECTURE.md` before changing pipeline or latency behavior.
- Read `docs/TEST_CHECKLIST.md` before changing appointment, FAQ, reminder, records, escalation, or end-call flows.
- Read `docs/PRIVACY_REVIEW.md` before sharing logs or screenshots.

## Before Opening a Pull Request

- Run the test suite.
- Run the health check after provider or startup changes.
- Add or update docs for new caller-facing behavior.
- Keep commits small enough to review independently.
