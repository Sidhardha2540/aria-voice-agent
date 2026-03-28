# Aria — AI Healthcare Receptionist

A **voice-first AI receptionist** for medical clinics. Callers talk naturally in their browser; Aria books appointments, answers FAQs, recognizes returning callers, and escalates to staff when needed. Built for **low latency** and **conversational feel** using real-time streaming (STT → LLM → TTS) over WebRTC.

---

## Features

| Feature | Description |
|--------|-------------|
| **Appointments** | Book, reschedule, cancel; check availability; list your upcoming appointments by phone. |
| **Doctors** | List doctors (optionally by specialty) — "Who do you have?" |
| **Clinic FAQ** | Hours, address, insurance, parking, services, pre-visit instructions. |
| **Medical records** | Request a copy (pickup or send); staff fulfill within ~5 business days. |
| **Reminders** | Request SMS/email reminder for an existing appointment (~24h before). |
| **Returning callers** | Recognizes callers by phone and personalizes (e.g. “Welcome back, Jane”). |
| **Escalation** | Transfers to human staff with a ticket (medical advice, billing, complaints, or “I want a person”). |
| **End call** | When the caller says goodbye or sounds satisfied, Aria says a short sign-off and ends the call. |
| **Latency tracking** | Per-turn breakdown (VAD, STT, LLM, TTS, infra) and session summaries (p95/p99) in `data/latency_log.jsonl`. |
| **Learn from feedback** | Outcomes from each call are stored; the next call’s system prompt includes condensed “learn from recent calls” so the agent improves over time. |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Pipeline** | [Pipecat](https://pipecat.ai/) — real-time voice orchestration |
| **Transport** | SmallWebRTC — browser ↔ server audio (no Daily/Twilio key required) |
| **STT** | [Deepgram](https://deepgram.com/) Nova-2 (streaming) |
| **LLM** | [OpenAI](https://openai.com/) (e.g. `gpt-4o-mini`) — conversation and function calling |
| **TTS** | [Cartesia](https://cartesia.ai/) — streaming text-to-speech |
| **VAD** | Silero — voice activity detection |
| **Database** | SQLite (aiosqlite); optional PostgreSQL for production |
| **Runtime** | Python 3.11+, [uv](https://github.com/astral-sh/uv) or pip |

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **API keys:** [Deepgram](https://deepgram.com/), [OpenAI](https://platform.openai.com/), [Cartesia](https://cartesia.ai/)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/aria-voice-agent.git
cd aria-voice-agent
uv sync
# or: pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:

- `DEEPGRAM_API_KEY` — STT
- `OPENAI_API_KEY` — LLM
- `CARTESIA_API_KEY` — TTS

### 3. Seed the database

```bash
uv run python scripts/seed_db.py
```

This creates doctors, sample availability, and clinic info in `data/aria.db`.

### 4. Run the bot

```bash
uv run python -m agent.bot -t webrtc
```

Then open **http://localhost:7860/client** in your browser and click **Call** to start a voice session.

---

## Project Structure

```
aria-voice-agent/
├── agent/
│   ├── bot.py              # Entry point, pipeline run, latency observer, greeting
│   ├── config.py           # Pydantic settings (.env)
│   ├── prompts.py          # System prompt and greeting
│   ├── learning.py         # Per-call feedback → "learn from recent calls"
│   ├── latency_tracker.py  # Per-turn breakdown + session summary (JSONL)
│   ├── core/               # Pipeline, context trimmer, errors
│   ├── database/           # Manager, repositories, models, seed
│   ├── tools/              # Tool schemas + handlers (appointments, escalation, end_call, …)
│   ├── transport/          # WebRTC (and optional Twilio/Daily) factory
│   └── observability/     # Health check
├── data/
│   ├── aria.db             # SQLite DB (doctors, appointments, callers)
│   ├── metrics.jsonl      # Per-call metrics
│   ├── feedback.jsonl      # Per-call outcomes for learning
│   └── latency_log.jsonl   # Per-turn latency breakdown + session summaries
├── docs/
│   ├── TEST_CHECKLIST.md   # How to test each tool and flow
│   ├── MCP_AND_MEMORY.md   # MCP tools & Mem0 memory (assessment)
│   └── ROADMAP.md         # Implementation roadmap
├── scripts/
│   ├── seed_db.py          # Seed doctors and clinic data
│   └── healthcheck.py     # Dependency health check
├── .env.example
├── pyproject.toml
└── ARCHITECTURE.md         # Full architecture and latency tradeoffs
```

---

## Configuration

Key environment variables (see `.env.example` for the full list):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | **Required.** OpenAI API key. |
| `DEEPGRAM_API_KEY` | — | **Required.** Deepgram API key. |
| `CARTESIA_API_KEY` | — | **Required.** Cartesia API key. |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model (e.g. `gpt-4o` for higher quality). |
| `DEEPGRAM_UTTERANCE_END_MS` | 500 | Silence duration before end-of-utterance (lower = faster, more cut-offs). |
| `DEEPGRAM_ENDPOINTING` | 200 | Endpointing sensitivity. |
| `TTS_LOW_LATENCY` | `true` | `true` = token-mode TTS (faster), `false` = sentence-mode (more natural). |
| `ENABLE_LEARN_FROM_FEEDBACK` | `true` | Inject “learn from recent calls” into the system prompt. |
| `ENABLE_DUAL_LLM` | `false` | Route simple vs complex turns to different models. |

---

## Testing the Bot

- **Tools:** Aria can check availability, book/reschedule/cancel appointments, look up callers, get clinic info, escalate to a human, and end the call when you’re satisfied.
- **Example flows:** “I need an appointment with a dermatologist” → pick slot → give name and phone → confirm → booked. Or: “What are your hours?” / “Thanks, that’s all” → end call.
- **Full checklist:** See [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) for tool-by-tool test cases and example phrases.

---

## Latency and Diagnostics

- **Target:** After-STT latency (time from “transcript ready” to “bot speaking”) aims for **200–300 ms** (natural conversation gap).
- **Per turn:** The pipeline logs `[LATENCY] After STT: Xms` and a breakdown table (VAD, STT, LLM TTFT, TTS TTFB, infra) with good/warning/bad ranges.
- **Logs:** `data/latency_log.jsonl` — one JSON object per turn plus a session summary at call end (min/max/mean/p95/p99 per stage, bottleneck).
- **Troubleshooting:** See [DIAGNOSTICS.md](DIAGNOSTICS.md) for pipeline flow, break points, and how to stay under 500 ms.

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | End-to-end architecture, pipeline stages, latency vs quality. |
| [DIAGNOSTICS.md](DIAGNOSTICS.md) | Where the pipeline can break, latency targets, learning-from-feedback. |
| [docs/TOOLS.md](docs/TOOLS.md) | **All implemented tools** and **ideas for new tools** (list_doctors, get_my_appointments, refill, etc.). |
| [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md) | Tools and example test flows. |
| [docs/MCP_AND_MEMORY.md](docs/MCP_AND_MEMORY.md) | MCP for tools and Mem0 for memory (assessment). |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branch naming, commits, and pull requests. |

---

## License

See [LICENSE](LICENSE) in the repository.
