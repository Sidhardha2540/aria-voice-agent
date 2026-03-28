# Aria Voice Agent — Architecture

This document describes the current architecture of **Aria**, an AI voice receptionist for medical clinics. It is designed so anyone can understand how the system works end-to-end.

---

## 1. Overview

**Aria** is an AI voice receptionist that handles:

- **Appointment booking, rescheduling, and cancellation**
- **Clinic FAQs** (hours, address, insurance, services, parking)
- **Returning caller recognition**
- **Escalation to human staff** when requests are outside Aria's scope

The system uses real-time voice over WebRTC: the user speaks in their browser, and Aria responds with synthetic speech. All orchestration is done by **Pipecat**, which connects Speech-to-Text (STT), Large Language Model (LLM), and Text-to-Speech (TTS) services in a streaming pipeline.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER (Browser)                                       │
│                         http://localhost:7860/client                             │
└────────────────────────────────────────────┬────────────────────────────────────┘
                                             │ WebRTC (audio)
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        SMALL WEBRTC TRANSPORT                                     │
│              (Peer-to-peer, no Daily/Twilio keys; works on Windows)               │
└────────────────────────────────────────────┬────────────────────────────────────┘
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │              PIPECAT PIPELINE                   │
                    │  ┌──────┐  ┌──────┐  ┌────┐ ┌────────────┐ ┌────┐ ┌────┐ ┌──────┐ │
                    │  │Input │─►│ STT  │─►│User│─►│ContextTrim │─►│LLM │─►│TTS │─►│Output│ │
                    │  └──────┘  └──────┘  └────┘ └────────────┘ └──┬─┘  └────┘ └──────┘ │
                    │                          │                         │
                    │                    ┌─────┴─────┐                    │
                    │                    │  TOOLS    │                    │
                    │                    │ (DB ops)  │                    │
                    │                    └─────┬─────┘                    │
                    └─────────────────────────┼───────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────────────┐
                    │           SQLite (data/aria.db)                   │
                    │  doctors | appointments | callers | clinic_info  │
                    └─────────────────────────────────────────────────┘
```

---

## 3. Tech Stack

| Layer | Technology | Role |
|-------|------------|------|
| **Framework** | Pipecat | Orchestrates the real-time voice pipeline |
| **Transport** | SmallWebRTC | WebRTC for browser ↔ server audio (peer-to-peer, no Daily key) |
| **STT** | Deepgram Nova-2 | Speech-to-text (streaming) |
| **LLM** | Groq (Llama 3.1 8B Instant) | Conversation + function calling |
| **TTS** | Cartesia Sonic-3 | Text-to-speech (streaming) |
| **VAD** | Silero | Voice activity detection (when user stops speaking) |
| **Database** | SQLite (aiosqlite) | Doctors, appointments, callers, clinic FAQs |
| **Runtime** | Python 3.11+, uv | Package and process management |

---

## 4. Pipeline Flow (Frame-by-Frame)

The Pipecat pipeline is a linear chain of processors. Frames flow **downstream** (user → bot) and **upstream** (bot → user) as needed.

```
  Transport Input
        │
        ▼
  Deepgram STT         ◄── Raw audio in
        │
        ▼
  User Aggregator      ◄── Silero VAD (detects when user stops speaking)
        │
        ▼
  ContextTrimmer       ◄── Trims conversation history to last N turns (prevents slowdown)
        │
        ▼
  Groq LLM             ◄── Transcripts + tool results; generates reply or calls tools
        │
        ▼
  Cartesia TTS         ◄── Text → audio
        │
        ▼
  Transport Output     ◄── Audio out to browser
        │
        ▼
  Assistant Aggregator   (context tracking)
```

### Sequence for One User Turn

1. User speaks → microphone → Transport sends raw audio.
2. **STT** (Deepgram) converts audio to text (streaming + final).
3. **VAD** (Silero) detects when user stopped speaking.
4. **Turn release** → transcript goes to LLM.
5. **LLM** (Groq) may call tools (e.g. `check_availability`, `book_appointment`).
6. **Tools** read/write SQLite and return results.
7. **LLM** generates reply from tool output and context.
8. **TTS** (Cartesia) converts reply text to audio.
9. **Transport** sends audio to browser.

---

## 5. Components in Detail

### 5.1 Transport — SmallWebRTC

- **Role:** Real-time audio I/O between browser and server via WebRTC.
- **Why:** Peer-to-peer, no Daily/Twilio key required; works on Windows.
- **Entry:** `http://localhost:7860/client` → click **Call** to start a session.

### 5.2 Speech-to-Text (Deepgram)

- **Model:** Nova-2 (streaming, low latency).
- **Config:** `agent/bot.py` → `DeepgramSTTService`.
- **Env vars:** `DEEPGRAM_API_KEY`, `DEEPGRAM_UTTERANCE_END_MS`, `DEEPGRAM_ENDPOINTING`.
- **Defaults:** `utterance_end_ms=300`, `endpointing=100` (optimized for <300ms latency target).
- **Key setting:** `utterance_end_ms` = how long silence before finalizing transcript. Lower = faster turn release, but may cut off slow speakers.

### 5.3 Voice Activity Detection (Silero VAD)

- **Role:** Determines when the user has stopped speaking.
- **Config:** `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`.

### 5.4 Large Language Model (Groq)

- **Model:** Llama 3.1 8B Instant (default); optionally `llama-3.3-70b-versatile` for higher quality.
- **Config:** `agent/bot.py` → `GroqLLMService` (model, temperature=0.3, max_tokens=80).
- **Env vars:** `GROQ_API_KEY`, `GROQ_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `MAX_CONTEXT_TURNS`.
- **Behavior:** Short system prompt (~280 tokens); enforces accuracy, no hallucination, filler phrases before tools.

### 5.5 Text-to-Speech (Cartesia)

- **Model:** Sonic-3 (streaming).
- **Config:** `agent/bot.py` → `CartesiaTTSService` (voice, emotion="content", speed=1.05).
- **Env vars:** `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, `TTS_LOW_LATENCY`.
- **Modes:** `TOKEN` (default when `TTS_LOW_LATENCY=true`) for faster first audio; `SENTENCE` for more natural prosody.

### 5.6 Prompts

- **File:** `agent/prompts.py`
- **SYSTEM_PROMPT:** Persona, rules, flows, accuracy constraints.
- **GREETING_PROMPT:** Initial greeting when call connects.
- **Key rules:** Only use tool data; never invent; say "I don't know" when unsure; offer transfer for out-of-scope requests.

---

## 6. Tools (Function Calling)

The LLM calls tools to perform actions. Each tool is implemented in `agent/tools/` and wired to the LLM via Pipecat's function-calling schema.

| Tool | Purpose | Backend |
|------|---------|---------|
| `check_availability` | List open slots for a doctor/date | SQLite `doctors`, `appointments` |
| `book_appointment` | Create an appointment | SQLite `appointments` |
| `reschedule_appointment` | Change date/time of appointment | SQLite `appointments` |
| `cancel_appointment` | Cancel an appointment | SQLite `appointments` |
| `get_clinic_info` | FAQs (hours, address, insurance, etc.) | SQLite `clinic_info` |
| `lookup_caller` | Check if caller has called before | SQLite `callers` |
| `escalate_to_human` | Transfer to human staff | Logs reason; in production would trigger SIP transfer |

---

## 7. Database (SQLite)

- **Path:** `data/aria.db` (configurable via `DB_PATH`).
- **Access:** Async via `aiosqlite` — never block the voice pipeline.
- **Shared singleton:** `get_shared_db()` — one connection per process; tools all use it.
- **Pre-warming:** DB connection and caches loaded at startup before transport starts.
- **Caching:** `clinic_info` and `doctors` pre-loaded into `_clinic_cache` and `_doctors_cache`; tools read from memory, not DB.
- **WAL mode:** `PRAGMA journal_mode=WAL` for better concurrent reads.

### Tables

| Table | Purpose |
|-------|---------|
| `doctors` | id, name, specialization, available_days, slot_duration_minutes |
| `appointments` | id, doctor_id, patient_name, patient_phone, date, time, status |
| `callers` | phone_number, name, last_call_at, preferences, call_count |
| `clinic_info` | key-value store for hours, address, insurance, services, parking |

### Seeding

```bash
uv run python scripts/seed_db.py
```

---

## 8. Configuration (Environment Variables)

### Required

| Variable | Purpose |
|----------|---------|
| `DEEPGRAM_API_KEY` | Deepgram STT API key |
| `GROQ_API_KEY` | Groq LLM API key |
| `CARTESIA_API_KEY` | Cartesia TTS API key |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `CARTESIA_VOICE_ID` | (default Aria voice) | Cartesia voice ID |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model (e.g. `llama-3.3-70b-versatile` for higher quality) |
| `DB_PATH` | `data/aria.db` | SQLite database path |
| `PORT` | `7860` | Server port |
| `HOST` | `0.0.0.0` | Server bind address |

### Latency Tuning

| Variable | Default | Effect |
|----------|---------|--------|
| `DEEPGRAM_UTTERANCE_END_MS` | `300` | ms of silence before final transcript (lower = faster, may cut off) |
| `DEEPGRAM_ENDPOINTING` | `100` | Pause detection threshold |
| `TTS_LOW_LATENCY` | `true` | `true` = token streaming (default); `false` = sentence mode, more natural |
| `LLM_TEMPERATURE` | `0.3` | Lower = more factual, less creative |
| `LLM_MAX_TOKENS` | `80` | Max response tokens; shorter = faster TTS |
| `MAX_CONTEXT_TURNS` | `10` | Max user+assistant turns before trimming; prevents slowdown on long calls |

---

## 9. Latency

### Current Target: <300ms

The defaults are tuned for sub-300ms user→bot response time. **Actual latency** depends on network, geographic distance to Groq/Deepgram/Cartesia APIs, and whether tools are called. Check the terminal for `[LATENCY] User→Bot: X.XXs` on each turn.

### Optimized Breakdown (Target ~290ms)

| Phase | Approx. Time | Description |
|-------|--------------|-------------|
| User turn (STT finalization) | ~0.12 s | VAD + Deepgram (utterance_end=300ms, endpointing=100) |
| LLM TTFB | ~0.08 s | 8B-instant, short prompt, max_tokens=80 |
| TTS TTFB | ~0.09 s | Token streaming, speed=1.05 |
| **Total** | **~290 ms** | User stops speaking → Aria starts speaking (no tool calls) |

*With tool calls:* Add ~50–150ms per call (DB cached lookups are fast; check_availability does more work).

### Optimizations Applied

- `utterance_end_ms` 300, `endpointing` 100 — faster turn release (~400ms saved vs 1000/250)
- `llama-3.1-8b-instant` — ~200ms faster than 70B
- System prompt ~280 tokens — less to process (~30ms)
- `TTS_LOW_LATENCY=true` (TOKEN mode) — faster first audio (~90ms)
- `max_tokens` 80, `speed` 1.05 — shorter replies, quicker TTS (~60ms)
- DB pre-warm + clinic/doctors cache — no cold DB hits on first tool call (~50ms)
- `ContextTrimmer` — caps history so long calls don't slow down

### Lower Latency Options

- Reduce `DEEPGRAM_UTTERANCE_END_MS` (e.g. 300–400).
- Reduce `DEEPGRAM_ENDPOINTING` (e.g. 150).
- Set `TTS_LOW_LATENCY=true`.
- Use `GROQ_MODEL=llama-3.1-8b-instant`.
- Use filler phrases before tool calls (see prompts: "Let me check that for you").

### Latency vs Quality Tradeoffs

When you reduce latency, you give up something. Here is what each optimization costs:

| Optimization | Approx. Savings | What You Lose |
|--------------|-----------------|---------------|
| **utterance_end_ms** 1000→300 | ~400ms | **Cutoffs:** Slow speakers or those who pause mid-sentence may be cut off. Aria may start responding before the caller finishes. |
| **endpointing** 250→150 | ~50ms | **Over-sensitivity:** Short pauses (e.g. "I'd like... uh... an appointment") may trigger turn release too early. |
| **llama-3.1-8b-instant** vs 70B | ~150ms | **Reasoning:** 8B is less capable at complex multi-step booking, nuanced FAQs, or handling edge cases. Simpler queries are fine. |
| **TTS_LOW_LATENCY=true** (TOKEN mode) | ~100ms | **Prosody:** Slightly flatter, less natural intonation. Sentences may sound more choppy; emotion/emphasis is reduced. |
| **Filler before tools** | ~50ms perceived | **Verbosity:** Extra phrase ("Let me check") adds one short sentence. Improves perceived speed, not true pipeline latency. |

**Recommended — Balanced preset (~600–700ms):** `DEEPGRAM_UTTERANCE_END_MS=600`, `DEEPGRAM_ENDPOINTING=200`. Keep `GROQ_MODEL=llama-3.3-70b-versatile` and `TTS_LOW_LATENCY=false`. Lowers latency ~400ms with minimal quality loss.

**Aggressive preset (~330ms target):** Set all four: `DEEPGRAM_UTTERANCE_END_MS=300`, `DEEPGRAM_ENDPOINTING=150`, `GROQ_MODEL=llama-3.1-8b-instant`, `TTS_LOW_LATENCY=true`. Best for fast-paced, simple interactions. Expect more cutoffs and slightly less natural speech.

---

## 10. Project Structure

```
aria-voice-agent/
├── agent/
│   ├── bot.py           # Main pipeline (STT, LLM, TTS, transport)
│   ├── config.py        # Loads env vars
│   ├── context_manager.py  # ContextTrimmer — trims history to MAX_CONTEXT_TURNS
│   ├── prompts.py       # System prompt, greeting
│   ├── database/
│   │   ├── db.py        # Async SQLite wrapper
│   │   ├── models.py    # Data classes
│   │   └── seed.py      # Seed logic
│   └── tools/
│       ├── appointments.py   # Book, reschedule, cancel, availability
│       ├── clinic_info.py    # FAQs
│       ├── caller_memory.py  # Returning caller lookup
│       └── escalation.py    # Transfer to human
├── data/
│   └── aria.db         # SQLite DB (created on first run)
├── scripts/
│   └── seed_db.py      # Seeds doctors, sample data
├── .env                # API keys (gitignored)
├── .env.example        # Template for env vars
├── pyproject.toml      # Dependencies (pipecat, groq, aiosqlite, etc.)
└── ARCHITECTURE.md     # This document
```

---

## 11. How to Run

```bash
# Install dependencies
uv sync

# Seed database (first time)
uv run python scripts/seed_db.py

# Start the bot
uv run python -m agent.bot -t webrtc
```

Then open **http://localhost:7860/client** and click **Call**.

---

## 12. Design Decisions

| Decision | Rationale |
|----------|-----------|
| **SmallWebRTC** | Works on Windows; no Daily key; peer-to-peer. |
| **Groq 8B-instant** | Low-latency default; 70B available for higher quality when needed. |
| **Shared DB + caching** | Single connection; clinic_info and doctors pre-loaded at startup — no DB hits for common lookups. |
| **Async SQLite** | Non-blocking DB so voice pipeline stays responsive. |
| **Tool-only information** | No hallucination; answers only from clinic_info, appointments, etc. |
| **Temperature 0.3** | More factual, less creative; reduces fabrication. |
| **TOKEN TTS (default)** | Faster first audio; SENTENCE mode available for more natural prosody. |
| **ContextTrimmer** | Caps conversation history to prevent gradual slowdown over long calls. |
| **UserBotLatencyObserver** | Measures and logs latency; warns when above 300ms target. |

---

## 13. Observability

- **Logging:** Loguru (Pipecat default).
- **Latency:** `UserBotLatencyObserver` logs:
  - `[LATENCY] First bot speech (greeting)`
  - `[LATENCY] User→Bot` — warns if above 300ms target
  - `[LATENCY] Breakdown` (per-service TTFB, user turn, etc.)

---

**Related:** [docs/TOOLS.md](docs/TOOLS.md) lists every agent tool and backend.

*Last updated to reflect latency optimizations: <300ms target, 8B-instant, DB caching, ContextTrimmer, token TTS.*
