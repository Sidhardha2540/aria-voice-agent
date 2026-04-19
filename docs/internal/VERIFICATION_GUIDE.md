# Aria — Verification & Testing Guide

> A checklist for functionality, latency, edge cases, database, deployment, and architecture.

---

## 1. Functionality Testing

**Before you start:** Ensure the bot is running (`uv run python -m agent.bot -t webrtc`) and open http://localhost:7860/client.

### Booking an appointment

| Step | Say this | Expected |
|------|----------|----------|
| 1 | "Hi, I need to schedule an appointment" | Aria greets and asks what type of care |
| 2 | "I'd like to see a dermatologist" | Aria checks availability, offers slots |
| 3 | "Thursday at 2:30 works" | Aria confirms details |
| 4 | "Yes, that's right" | Aria books, gives confirmation and appointment ID |

### Rescheduling

| Step | Say this | Expected |
|------|----------|----------|
| 1 | "I need to reschedule my appointment" | Aria asks for appointment ID |
| 2 | "APT-1234" (use a real ID from a previous booking) | Aria asks for new date/time |
| 3 | "Friday at 10 AM" | Aria confirms and updates |

### Canceling

| Step | Say this | Expected |
|------|----------|----------|
| 1 | "I need to cancel my appointment" | Aria asks for appointment ID |
| 2 | "APT-1234" | Aria cancels and confirms |

### FAQs

| Say this | Expected |
|----------|----------|
| "What are your office hours?" | Mon–Fri 8am–6pm, Sat 9am–1pm |
| "What's your address?" | 123 Medical Center Dr, Suite 200 |
| "Do you accept my insurance?" | Lists Blue Cross, Aetna, United, Cigna, Medicare |
| "What services do you offer?" | General, cardiology, dermatology, pediatrics |

---

## 2. Latency

**What to expect:** First response ~500ms–1.5s (STT + LLM + TTS). Subsequent turns ~300–800ms.

**Rough breakdown:**
- Deepgram STT: ~100–200ms (streaming)
- Groq LLM: ~150–300ms (first token)
- Cartesia TTS: ~60–150ms (first audio)
- **Total:** ~300–650ms for a simple reply

**How to judge:** If Aria feels like a natural phone conversation (short pauses between turns), latency is good. If you wait 2+ seconds often, something may be wrong.

**Tips:** Shorter user inputs = faster responses. Tool calls (e.g. check_availability) add ~200–500ms.

---

## 3. Edge Cases to Try

| Scenario | What to do | Expected behavior |
|----------|------------|-------------------|
| **Interruption** | Start talking while Aria is speaking | She should stop or yield |
| **Unclear input** | Mumble or say something vague | She asks for clarification |
| **Out-of-scope** | "What's the capital of France?" | She offers to transfer to front desk |
| **No availability** | Ask for slots on a fully booked day | She suggests other dates or doctors |
| **Caller memory** | Call again with same "phone" (demo may not simulate this) | In production, "Welcome back!" for returning callers |
| **Upset caller** | "This is ridiculous!" | She responds with empathy and offers help |

---

## 4. Database Verification

**Where:** `data/aria.db` (SQLite)

### View appointments

In PowerShell (from project root):

```powershell
uv run python -c "
import asyncio
from agent.database.db import AsyncDatabase
from agent.config import DB_PATH

async def main():
    db = AsyncDatabase()
    await db.connect()
    async with db._conn.execute('SELECT id, patient_name, appointment_date, start_time, status FROM appointments ORDER BY created_at DESC LIMIT 10') as cur:
        rows = await cur.fetchall()
    for r in rows:
        print(r)
    await db.close()

asyncio.run(main())
"
```

### View doctors

```powershell
uv run python -c "
import asyncio
from agent.database.db import AsyncDatabase

async def main():
    db = AsyncDatabase()
    await db.connect()
    docs = await db.get_all_doctors()
    for d in docs:
        print(f'{d.id}: {d.name} - {d.specialization}')
    await db.close()

asyncio.run(main())
"
```

**What to check after a booking:** A new row in `appointments` with `status='booked'`.

---

## 5. Deployment (Production)

**Option A: Fly.io (recommended)**

1. Install Fly CLI: https://fly.io/docs/hands-on/install-flyctl/
2. `fly auth login`
3. Create `Dockerfile` and `fly.toml` (see build guide)
4. `fly launch` then `fly deploy`
5. Your bot runs on a public URL; point clients to it

**Option B: Docker anywhere**

```dockerfile
FROM python:3.12-slim
RUN pip install uv && uv pip install --system "pipecat-ai[deepgram,cartesia,openai,silero,webrtc,runner]" groq aiosqlite python-dotenv
COPY . /app
WORKDIR /app
EXPOSE 7860
CMD ["python", "-m", "agent.bot", "-t", "webrtc"]
```

**Important:** Set env vars (DEEPGRAM_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY) in Fly.io secrets or Docker. Never commit `.env`.

---

## 6. Architecture — Low-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER'S BROWSER                                     │
│  Microphone ───────────────────────────────────────────────► Speakers       │
│       │         WebRTC (SmallWebRTC) peer-to-peer connection    ▲            │
└───────┼──────────────────────────────────────────────────────┼─────────────┘
        │                                                        │
        ▼                                                        │
┌───────────────────────────────────────────────────────────────────────────────┐
│                        PIPECAT PIPELINE (agent/bot.py)                         │
│                                                                                │
│  transport.input() ──► STT (Deepgram) ──► Context ──► LLM (Groq) ──► TTS ──►   │
│       │                   │               aggregator     │       (Cartesia)   │
│       │                   │                    │         │            │       │
│       │                   │                    │         └──tools───►│       │
│       │                   │                    │              │       │       │
│       │                   │                    │              ▼       │       │
│       │                   │                    │        ┌──────────┐   │       │
│       │                   │                    │        │ SQLite   │   │       │
│       │                   │                    │        │ (aria.db)│   │       │
│       │                   │                    │        └──────────┘   │       │
│       │                   │                    │                         │       │
│       ▼                   ▼                    ▼                         ▼       │
│  transport.output() ◄────────────────────────────────────────────────────────  │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Flow in words:**
1. **Transport** receives raw audio from the browser (WebRTC).
2. **Deepgram STT** turns speech into text.
3. **Context aggregator** + **Silero VAD** decide when the user has finished speaking.
4. **Groq LLM** receives the text. It may call tools (e.g. `check_availability`, `book_appointment`).
5. Tools read/write **SQLite** and return text to the LLM.
6. **Cartesia TTS** turns the LLM’s reply into audio.
7. **Transport** sends audio back to the browser.

**Development runner:** Serves the web client at `/client` and handles WebRTC signaling so the browser can connect to the bot.

---

*Use this guide while testing Aria. Update it with your own notes as you go.*
