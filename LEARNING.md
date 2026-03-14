# Aria Voice Agent — Build Learning Guide

> **Your personal documentation.** This file grows as we build. Everything you learn goes here.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Folder & File Purposes](#folder--file-purposes)
3. [How the Pipeline Works](#how-the-pipeline-works)
4. [Key Concepts](#key-concepts)
5. [Verification & Testing](#verification--testing)
6. [What You Learned (Session Notes)](#what-you-learned-session-notes)

---

## Project Overview

**Aria** is an AI voice receptionist for medical clinics. It:
- Answers calls via web (WebRTC)
- Books, reschedules, cancels appointments
- Answers FAQs (hours, insurance, address)
- Uses real AI (speech-to-text → LLM → text-to-speech)
- Costs ~$25/month to run

**Tech flow:** Your microphone → STT (speech-to-text) → LLM (brain) → TTS (text-to-speech) → Speaker

---

## Folder & File Purposes

| Path | Purpose |
|------|---------|
| `agent/` | All Python code for the voice agent — config, bot, tools, processors |
| `agent/config.py` | Loads `.env` and holds API keys, DB path, voice ID — one place for all settings |
| `agent/__init__.py` | Makes `agent` a Python package so you can `from agent.config import ...` |
| `frontend/` | React web UI for the demo (call button, transcript, appointment card) |
| `scripts/` | One-off scripts (seed DB, generate fillers) |
| `tests/` | Automated tests |
| `LEARNING.md` | This file — your learning notes |
| `VERIFICATION_GUIDE.md` | Testing checklist: functionality, latency, edge cases, DB, deployment, architecture |

### What we created in Phase 1

| File | What it does |
|------|--------------|
| `pyproject.toml` | Defines the Python project, dependencies (Pipecat, Groq, aiosqlite, etc.), and Python version. Like `package.json` for Python. |
| `.env.example` | Template for API keys. You copy it to `.env` and fill in real keys. `.env` is never committed to git. |
| `.env` | Your actual keys (you create this). Never share or push it. |

---

## How the Pipeline Works

1. **Transport input** — SmallWebRTC (peer-to-peer WebRTC) receives your microphone audio.
2. **Deepgram STT** — Converts speech to text (streaming, ~90ms latency).
3. **Context aggregator** — Collects what you said; Silero VAD detects when you stop speaking.
4. **Groq LLM** — Decides what to say; can call tools (check_availability, book_appointment, etc.).
5. **Cartesia TTS** — Converts LLM text to natural speech.
6. **Transport output** — Sends audio back to your speakers.

When you say "I need to see a dermatologist," the LLM calls `check_availability("dermatology", "next available")`, gets slots from the DB, and speaks them naturally.

---

## Key Concepts

### Phase 1: Project structure

- **pyproject.toml** — Modern Python config file. Lists dependencies so `uv` or `pip` can install them. `[project]` defines name, version, what Python version you need.
- **Environment variables** — Secret keys (API keys) live in `.env`. Code reads them via `os.getenv()`. We use `python-dotenv` to load `.env` when the app starts.
- **config.py** — Single source of truth for all settings. Instead of scattering `os.getenv()` everywhere, we read once in config and import `config.DEEPGRAM_API_KEY`, etc.

### Phase 2: Database layer

| File | Purpose |
|------|---------|
| `agent/database/models.py` | **Dataclasses** — Python classes that describe the shape of data. `Doctor`, `Appointment`, `Caller`, `ClinicInfo`. Not the actual DB tables, just how we think about the data in code. |
| `agent/database/db.py` | **AsyncDatabase** — Talks to SQLite. All methods are `async` because blocking would freeze the voice pipeline. Uses `aiosqlite` (async SQLite). Creates tables, does CRUD for doctors, appointments, callers, clinic_info. |
| `agent/database/seed.py` | **Seed data** — Puts demo data in the DB: 4 doctors, 6 sample appointments, clinic FAQs (hours, address, insurance, etc.). Run once. |
| `scripts/seed_db.py` | Convenience script — Just runs `seed()`. Use: `uv run python scripts/seed_db.py` |

**Why async?** Voice agents process audio in real time. If we used blocking `sqlite3`, every DB call would pause the entire pipeline — no audio in or out until the query finishes. `aiosqlite` runs DB ops in the background.

### Phase 3 & 4: Core pipeline + tools

| File | Purpose |
|------|---------|
| `agent/prompts.py` | **System prompt** — Tells Aria who she is, how to speak (short, natural, contractions), and the appointment flow. Voice-optimized so output sounds spoken, not written. |
| `agent/bot.py` | **Main pipeline** — Connects everything: SmallWebRTC transport → Deepgram STT → Silero VAD → Groq LLM (with tools) → Cartesia TTS → back to transport. Uses the development runner; works on Windows, Mac, Linux. |
| `agent/tools/appointments.py` | **Appointment tools** — `check_availability`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`. Each queries the DB and returns natural-language text for the LLM to speak. |
| `agent/tools/clinic_info.py` | **FAQs** — `get_clinic_info(topic)` for hours, address, insurance, services, parking. |
| `agent/tools/caller_memory.py` | **Caller memory** — `lookup_caller(phone)` to detect returning callers. |
| `agent/tools/escalation.py` | **Transfer** — `escalate_to_human(reason)` when Aria can't help. |

**Pipeline flow:** Mic → STT (speech to text) → Context aggregator (collects what user said) → LLM (decides response, may call tools) → TTS (text to speech) → Speaker.

**Function calling:** The LLM gets a list of tools (schemas). When it wants to check availability or book an appointment, it "calls" the tool. Our Python handlers run, query the DB, and return a string. The LLM turns that into natural speech.

---

## Verification & Testing

See **VERIFICATION_GUIDE.md** for:
- Functionality checklist (booking, rescheduling, FAQs)
- Latency expectations
- Edge cases to try
- Database verification commands
- Deployment (Fly.io, Docker)
- Architecture diagram

---

## What You Learned (Session Notes)

*(Quick notes from each build session — what clicked, what was confusing.)*

---

*Last updated: SmallWebRTC migration + verification guide*
