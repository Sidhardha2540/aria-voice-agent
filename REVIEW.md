# Aria — Production Readiness Review

This is an honest engineering review focused on three things you asked about:

1. **Real bugs** (things that are broken or will break)
2. **Conversation feel** (why it sounds robotic + concrete fixes)
3. **Production readiness** — scalability, reliability, security, HIPAA

Each item has a file reference and a concrete fix you can paste into Cursor.

---

## TL;DR — Honest Assessment

Your repo is **a strong portfolio project** — the architecture is clean, separation of concerns is good, and the engineering instincts (latency tracking, error boundaries, pydantic validation, dual-LLM routing, emotion mapping) are exactly what recruiters want to see. But it is **not production-ready in any strict sense**, and two things make that especially true for a **medical** use case: (a) there are real bugs, including one that probably breaks booking entirely, and (b) there is no HIPAA posture whatsoever (PII in plaintext logs, unencrypted DB, no auth, no audit trail).

For a LinkedIn demo this is fine — and actually a great story to tell. The trick is to fix the critical bugs, polish the conversation feel, and reframe the README honestly: "**a working prototype** of a voice-first AI receptionist, designed with latency, reliability, and extensibility in mind." Then in a follow-up section, call out what you'd add for production (HIPAA, multi-tenant, auth, real telephony). Recruiters love candidates who know what they don't know.

---

## 1. Critical Bugs (fix before demo)

### 🔴 1.1 `book_appointment` is almost certainly broken — parameter `date` shadows `datetime.date`

**File:** `agent/tools/appointments.py:167-198`

The function parameter is `date: str`, but inside the try block:

```python
parsed = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
today = date.today()   # ← 'date' here is the string param, not datetime.date
```

`date.today()` on a string raises `AttributeError`, which is **not** caught by the `except (ValueError, IndexError)`. It bubbles up to `safe_tool_call` which returns the generic "I ran into an issue while booking that" message. **So every valid booking fails.**

**Fix:** rename the parameter, or alias the import.

```python
# Option A — rename param (preferred; also more descriptive)
async def book_appointment(doctor_id: int, patient_name: str, patient_phone: str,
                           appointment_date: str, time: str, notes: str = "") -> str:
    ...
    date_str = appointment_date.strip()
    ...
    today = date.today()   # now 'date' is the class again
```

You'll need to update the handler in `agent/tools/handlers.py:49-55` and the tool schema in `agent/tools/registry.py:26-38` to match.

### 🔴 1.2 `datetime.utcnow()` is deprecated in Python 3.12+

**Files:** `agent/database/db.py:80`, `agent/database/repositories/callers.py:27`, `agent/services/reminders.py:30`, `agent/latency_tracker.py:237,319`

In Python 3.12 `utcnow()` emits a DeprecationWarning and will be removed. Also, it returns a naive datetime (no timezone), which is a common bug source.

**Fix:** `datetime.now(timezone.utc).isoformat()` — drop the `+ "Z"` suffix because `isoformat()` on an aware datetime already includes `+00:00`. (If you want the `Z` specifically for Mongo/JS compatibility, do `.isoformat().replace("+00:00", "Z")`.)

### 🔴 1.3 Double-booking race condition

**File:** `agent/tools/appointments.py:212-227`

```python
existing = await db.get_appointments_by_doctor_and_date(doctor_id, date_str)
for a in existing:
    if a.start_time == time:
        return "That slot was just taken. ..."
apt_id = generate_appointment_id()
await db.create_appointment(...)
```

Classic TOCTOU. Two callers booking the same slot at the same time both pass the check, both insert. **Fix options:**

- **Quickest:** add a `UNIQUE(doctor_id, appointment_date, start_time) WHERE status='booked'` partial index and catch the IntegrityError on insert. In SQLite, a unique index on `(doctor_id, appointment_date, start_time, status)` works.
- **Proper:** wrap check + insert in a DB transaction (`BEGIN IMMEDIATE` for SQLite, `SELECT ... FOR UPDATE` for Postgres).

The same issue applies to `reschedule_appointment` (line 257-263).

### 🔴 1.4 Duplicate / conflicting exit cleanup

**Files:** `agent/bot.py:143-164` and `agent/main.py:13-32`

Both files register `atexit` handlers that call `db_manager.shutdown()` inside a freshly-created `asyncio.new_event_loop()`. When the process exits, both fire. The second one runs on an already-closed connection and logs a debug exception. It's harmless but noisy — pick one location (I'd keep it in `main.py`, the actual entrypoint, and delete `_register_exit_cleanup()` from `bot.py`).

### 🟡 1.5 `end_call` races against TTS playback

**File:** `agent/tools/handlers.py:180-191`

```python
async def _disconnect_later():
    await asyncio.sleep(2.0)
    await task.cancel()
```

If the goodbye message is longer than ~2s once TTS speaks it, the call gets cut off mid-sentence. Cartesia streaming TTS takes variable time depending on the length.

**Fix:** listen for `BotStoppedSpeakingFrame` (Pipecat emits this when TTS finishes) and disconnect then, with a safety timeout as fallback. Cleaner approach: push a `EndFrame()` or `StopInterruptionFrame()` after the TTS result rather than sleeping.

### 🟡 1.6 `get_system_prompt()` reads `feedback.jsonl` synchronously on every call

**File:** `agent/prompts.py:84-96` + `agent/learning.py:82-87`

Every new call opens and reads the whole feedback file synchronously from an async context. At 50 entries this is fast, but the file grows forever (no cap, no rotation). After thousands of calls this becomes a blocking I/O hit on the cold start of each session.

**Fix:** read the file once at startup, cache the parsed learnings, invalidate when a call ends (you already append at call end). Or cap `feedback.jsonl` with log rotation.

### 🟡 1.7 `SYSTEM_PROMPT = get_system_prompt()` at module import

**File:** `agent/prompts.py:101`

Evaluated once at import time — so the "Today is Monday, …" embedded in it is stale forever (until process restart). You do re-call `get_system_prompt()` inside `create_pipeline`, so it's actually fine, but `SYSTEM_PROMPT` is a footgun. Delete the line if nothing imports it (grep shows nothing does).

### 🟡 1.8 `_convert_query_to_postgres` is fragile

**File:** `agent/database/manager.py:15-22`

Naive `re.sub(r"\?", ...)` — if a query string ever contains a literal `?` (unlikely here, but it's brittle). And it rewrites `?` inside string literals too. Consider using `asyncpg` placeholders natively instead of translating SQLite queries, or use SQLAlchemy Core for portability.

### 🟡 1.9 `asyncio.get_event_loop()` is deprecated when there's no running loop

**File:** `agent/metrics.py:184`, `agent/intent_router.py:127`

Use `asyncio.get_running_loop()` inside async functions.

---

## 2. Conversation Quality — Why It Feels Robotic

This is the section you care most about. The architecture is sound; the feel is off because of **six specific issues**. Fix them in order and you'll feel the difference immediately.

### 2.1 The system prompt is a wall of rules, not a character

**File:** `agent/prompts.py:14-82`

Right now the prompt reads like a spec sheet: "VOICE STYLE / NO REPETITION / PACING / WHEN INTERRUPTED / FILLER DURING WAITS / DATES / CLINIC INFO / SMART ROUTING / TOOLS / AFTER EVERY TOOL CALL / BOOKING FLOW / NAMES AND SPELLING / EMPATHY / ESCALATION / ACCURACY / RELIABILITY / CONCLUSION". That's 16 rule blocks in ALL CAPS. LLMs respond better to **character + examples + light rules**.

**Fix:** rewrite the prompt around a short persona, then embed rules as **conversational examples** rather than decrees. Suggested structure:

```
You are Aria, a warm, unhurried receptionist at Greenfield Medical Center.
You have the calm confidence of someone who has done this job for years.

You sound like this:
  Caller: "Hi, I need an appointment."
  You: "Sure, I can help with that. What's going on?"
  Caller: "Rash on my arm, been a few days."
  You: "Got it — sounds like dermatology. Dr. Rodriguez handles that.
       Let me check her schedule for you."
       [calls check_availability]

You do NOT sound like this:
  "I will now check the available appointment slots. Please hold."
  "I have found the following options for you:"

Rules of thumb:
- Max two short sentences per turn. Use contractions.
- Say dates conversationally: "Wednesday the 19th at 3 PM" — never "2026-04-19T15:00".
- Before any tool call, one short filler: "Let me check that" / "One sec" / "Pulling it up".
- After a tool call, relay the result in plain language. Never leave silence.
- Ask one thing at a time. Name first; phone on the next turn.
- If someone interrupts or corrects you, start with "Sure," or "Got it," or "No problem."
  Then continue from where you were — don't restart.

Today is {today}.
{clinic_info}
{doctors_list}
{tool_hints}
{learn_from_recent_calls}
```

This reduces token count too (which helps LLM TTFT). Keep hard rules (escalation boundaries, booking confirmation flow) but phrase them positively.

### 2.2 No acknowledgement phrases ("Sure", "Got it", "Of course")

These are what make speech feel human. The prompt mentions them but LLMs often skip them. Force the issue by **prepending an acknowledgement at the code level** for any turn that follows a user interruption. You already have `BargeInLogger`; extend it so that after an interruption, the next LLM response is prefixed with a cheap acknowledgement (randomly chosen from `["Sure,", "Got it,", "Of course,", "No problem,"]`).

This is the single biggest "humanizing" lever. Real receptionists always acknowledge.

### 2.3 No backchanneling — the void during long user turns

**File:** `agent/backchanneling.py` (TODO stub)

You left this unimplemented, which is the right call (it's hard). But **call it out in your LinkedIn post** as future work — it's an impressive thing to know exists. For the demo, a cheaper alternative: when the user says something long, occasionally prefix Aria's response with "Okay, so—" or "Mhm, got it—" to simulate the acknowledgement retroactively.

### 2.4 The emotion mapper never speeds up or slows down real speech

**File:** `agent/emotion_mapper.py`

You emit `<emotion>` and `<speed>` SSML-style tags inside the text. **Cartesia's API does not parse SSML inside the text stream** — these tags get spoken literally as `<emotion value="happy" />` or silently stripped. To actually change voice emotion per-sentence you need to update Cartesia's `generation_config` dynamically, which is a different API surface.

**Fix options:**
- Quickest: delete the SSML tagging entirely and just set one emotion/speed in `generation_config` at pipeline creation (`content`, 1.05 is fine).
- Better: wrap the `CartesiaTTSService` and call its `update_generation_config` (or recreate the service) before emotionally charged lines. This is more work; for the demo, option A is honest and doesn't add latency.

**Also:** the fact that you tried this at all is great portfolio material — talk about it as "we prototyped per-sentence emotion modulation and learned the TTS boundary was the wrong place to do it; moved it to VAD-aware fill phrases instead."

### 2.5 The filler "Let me check that for you" is spoken *before* the tool runs — which is good — but it gets concatenated into the same LLM response that then *also* answers after. The TTS sounds like "Let me check that for you [1.2s pause] She has openings..."

The LLM is told to say the filler, then actually run the tool, then say the result — but because OpenAI streams the whole response as one turn, the filler and the answer are both in the same LLMFullResponse, so the pause between them feels unnatural.

**Fix (portfolio-worthy):** use a **dedicated pre-tool filler audio clip**. Pre-record (or pre-synthesize once at startup) 3-4 short WAV clips: "one sec", "let me check", "pulling that up". When the LLM emits a function call, your pipeline pushes the clip audio frames immediately, then runs the tool, then streams the LLM's response. This is what commercial voice agents (Retell, Vapi) actually do. It's a great engineering story.

### 2.6 Name spelling correction flow is brittle

**File:** `agent/prompts.py` (the NAMES AND SPELLING rule)

You've given the LLM a lot of rules for letter-by-letter spelling, but Deepgram Nova-2 already does pretty good name recognition. The current prompt handles "J E E V A N" but not common things like "it's with a K not a C" mid-name, or accented names, or last-name-first conventions.

**Fix:** stop trying to handle spelling in the prompt. Instead, after the LLM captures a name, **always** read it back and confirm once: "Got it — Jeevan, J-E-E-V-A-N, is that right?". If the caller says "no", just accept their correction verbatim on the next turn. No logic needed.

---

## 3. Reliability Issues

### 3.1 No graceful degradation when a provider goes down

If Deepgram, OpenAI, or Cartesia has an outage, the whole call dies. There's no fallback provider, no "reconnection on transient failure" logic. For a demo this is fine but worth noting in your LinkedIn post as "planned: multi-provider failover".

### 3.2 `safe_tool_call` has a 12-second timeout, but no retry

If the first DB query hangs (e.g. SQLite lock contention), the caller hears "I'm having trouble looking that up" — even if the second try would have worked instantly. A quick retry-with-exponential-backoff (up to 2 tries, 100ms and 300ms) covers transient flakes without adding perceived latency.

### 3.3 No circuit breaker around tool calls

If OpenAI is slow and returning 500s for 3 consecutive calls, the 4th caller still waits 12s. A simple circuit breaker (e.g. `after 3 consecutive failures, fail fast for 30s`) prevents cascading badness.

### 3.4 The metrics are **fire-and-forget background tasks** with no error handling

**File:** `agent/metrics.py:194`

```python
asyncio.create_task(_write_metrics_async(d, jsonl_path))
```

If the event loop is cancelling (because the call ended), this task may be silently cancelled with no log. Add `task.add_done_callback(lambda t: t.exception() and logger.error(...))` or await it with a timeout during disconnect.

### 3.5 Single DB connection for SQLite is a concurrency floor

**File:** `agent/database/manager.py:56`

One connection + WAL mode is fine for single-writer / many-readers, but every `execute_write` blocks other writes. If two callers book at the same time, they serialize on the connection. For demo this is fine; for production say "Postgres pool" (which you already have code for — good!).

### 3.6 No structured request/response correlation ID in logs

Every log line includes `session_id=...` sometimes but not consistently (search for `session=test-session` — it's passed to `safe_tool_call` but not threaded everywhere). For prod debuggability, put the session_id in a contextvar and inject it into loguru's context.

### 3.7 The `end_call` tool is the only way to gracefully disconnect

If the caller hangs up first (closes the browser tab), `on_client_disconnected` fires and things clean up. But if the LLM fails to call `end_call` at the end of a satisfied conversation, the call just sits there forever. Add a per-call inactivity timeout (e.g. 30s of silence → polite sign-off → disconnect).

---

## 4. Scalability Issues

### 4.1 Global singletons won't multi-tenant

**File:** `agent/database/manager.py:216`, `agent/database/db.py:17`

`db_manager` and `_shared_instance` are module-level globals. Perfect for single-clinic single-server, impossible to run two clinics from the same process. Not a bug — worth saying in README "designed for single-tenant deployment; multi-tenant requires per-request scoping."

### 4.2 The `_last_emotion` state in the pipeline is per-pipeline, not per-tenant

**File:** `agent/core/pipeline.py:130-131`

Fine right now because each WebRTC connection gets its own pipeline. Worth a comment.

### 4.3 Scaling telephony means sticky sessions

WebRTC is peer-to-peer so a single Aria process must own both sides of the audio for the life of the call. For horizontal scaling you need a signaling server + session affinity, or a SIP gateway. Again, not a bug — a discussion point.

### 4.4 `feedback.jsonl` and `metrics.jsonl` grow forever

No log rotation, no S3 upload, no purging of PII. In production this becomes a HIPAA leak vector (see §5). For now: add log rotation (`logrotate`, or a size-based roll).

### 4.5 The healthcheck doesn't test external APIs

**File:** `agent/observability/health.py:39-41`

The health check only checks that API keys are *present*, not that Deepgram/OpenAI/Cartesia are reachable. For a demo that's fine; for prod you'd want a lightweight ping (e.g. Deepgram's `/v1/projects` returns 200 if the key is valid and the service is up).

### 4.6 `check_availability` iterates all doctors, then for each one iterates 14 days, 16 slots/day, doing a DB roundtrip per (doctor, date)

**File:** `agent/tools/appointments.py:127-142`

For 4 doctors × 5 days = 20 DB roundtrips per `check_availability` call. At SQLite speeds (sub-ms) it's fine, but over a Postgres RTT it's 20 × 20ms = 400ms added to LLM→TTS latency. **Fix:** pull all appointments in one query: `SELECT ... WHERE doctor_id IN (...) AND appointment_date IN (...)`.

---

## 5. Security & HIPAA — The Big One

This is the section where "medical clinic receptionist" actually matters. **None of this has to be solved for a LinkedIn demo**, but you should acknowledge it in the README's "what's next" section — that's the mark of someone who understands the domain.

### 5.1 PII is logged in plaintext

- `agent/tools/escalation.py:35` logs name + phone in the escalation ticket
- `agent/learning.py:63` logs escalation reason (may contain PII)
- `agent/metrics.py:193` writes tool-call sequences to `metrics.jsonl`
- `agent/services/reminders.py:29-36` writes name + phone to `reminder_requests.jsonl`
- Every tool call logs full arguments via `safe_tool_call`'s error path

**HIPAA requires** audit trails but **also** requires PII to be encrypted or redacted in non-production systems. **Fix for now:** add a `redact_pii()` helper that masks phone numbers to last 4 digits and names to initials in logs, but stores full data only in the DB (which should be encrypted at rest).

### 5.2 No authentication on the WebRTC endpoint

Anyone who hits `http://your-server/client` can initiate a call. For a demo fine; for production you'd want a per-caller token, rate limiting, and ideally a SIP gateway that's authenticated.

### 5.3 Unencrypted SQLite / no encryption at rest

`data/aria.db` stores patient names, phones, appointments, preferences in plaintext. For prod: use `sqlcipher` for SQLite, or encrypted disks + Postgres with TLS.

### 5.4 No TLS termination in the stack

Dockerfile exposes 7860 raw. For prod you'd put it behind nginx/Caddy with TLS, or Cloudflare Tunnel. For demo, localhost is fine.

### 5.5 `docker-compose.yml` has hardcoded DB password

**File:** `docker-compose.yml:8,26-27`

`postgresql://aria:aria_pass@postgres:5432/aria_db`. Move to env vars.

### 5.6 No consent flow / no HIPAA Notice of Privacy Practices

Real medical systems need to deliver NPP to every caller. Aria doesn't. Acknowledge this as future work.

### 5.7 `pyproject.toml` pins `pipecat-ai>=0.0.50`

Pipecat is pre-1.0. Unpinned major version → breaking changes possible. Pin to a minor range: `pipecat-ai[...]>=0.0.50,<0.1.0` at least, and commit `uv.lock` (which you do — good).

### 5.8 No rate limiting

Someone could spam the WebRTC endpoint and burn your API credits in minutes. Add basic per-IP rate limiting at the transport layer (nginx, Cloudflare, or a Python middleware).

### 5.9 `.env` might contain real keys if you ever commit it

`.env` is gitignored correctly. Just audit your git history to make sure you never accidentally committed it pre-gitignore: `git log --all --full-history -- .env`. If it's in history, rotate those keys immediately.

---

## 6. Testing Gaps

**File:** `tests/test_errors.py` is the only test file and it covers 3 helpers. Otherwise:

- No tests for any service (`appointments`, `clinic_info`, `escalation`)
- No tests for the DB repositories
- No tests for `FunctionCallFilter` (regex-based, easy to break)
- No tests for `IntentRouter` classifier (which has a bunch of regexes)
- No end-to-end tests simulating a conversation

**Fix for demo:** add 6-8 high-value tests. In priority:

1. `test_book_appointment_happy_path` — seeds DB, calls book, asserts spoken message + DB state
2. `test_check_availability_no_slots` — asserts the right fallback message
3. `test_function_call_filter_strips_markup` — feed a stream with `<function=...>...</function>`, assert TTS never sees it
4. `test_intent_router_classifies_yes_no_as_simple`
5. `test_intent_router_classifies_multi_constraint_as_complex`
6. `test_emotion_mapper_returns_happy_for_booked`
7. `test_safe_tool_call_timeout_returns_spoken_error`
8. `test_concurrent_booking_conflict_detected` (once you fix the race condition)

Even 8 tests is a big jump from 5 and looks great on a LinkedIn post.

---

## 7. LinkedIn / Demo Polish

### 7.1 Record a demo that shows the latency numbers

Your `[LATENCY]` console output is beautiful. Include a screenshot or clip of the "VOICE-TO-VOICE: 280ms ✅ good" box-drawn table in your LinkedIn post — that's concrete proof of engineering craft. Most voice demo posts just show the conversation; showing the latency instrumentation is distinctive.

### 7.2 Show the learn-from-feedback loop in action

Record two calls: the first triggers an edge case (e.g. caller interrupts during spelling), the second call avoids the same mistake because `LEARN FROM RECENT CALLS` was injected. This is a genuinely novel pattern and worth 30 seconds of the demo.

### 7.3 Put the README's "Documentation" section up top

Your `ARCHITECTURE.md`, `DIAGNOSTICS.md`, `docs/TOOLS.md`, and `docs/ROADMAP.md` are honestly more impressive than the code. Link to them prominently so recruiters click through.

### 7.4 Delete or rewrite `IMPROVEMENT_PROMPTS.md`, `LEARNING.md`, `VERIFICATION_GUIDE.md`, `CHANGELOG.md`

These look like internal scratchpads (IMPROVEMENT_PROMPTS is 19KB of raw prompts to paste into an LLM). For a public repo they clutter the root. Move them to `docs/internal/` or delete.

### 7.5 Add a demo GIF or 30-second video at the top of README

`![Aria Demo](docs/demo.gif)` at the top of README is what makes a GitHub repo shareable on LinkedIn.

### 7.6 Honest `## Status` section in README

Right before the Features table, add:

```markdown
## Status

Aria is a **working prototype**, not a production system. It demonstrates:
- Real-time voice pipeline (STT → LLM → TTS) under 500ms latency
- Tool-calling for booking, FAQs, escalation, memory
- Per-call latency instrumentation and learn-from-feedback loop

Not production-ready: no HIPAA posture, no authentication, single-process,
SQLite at rest. See the roadmap for what a production deployment would add.
```

This is the **single most important paragraph** for recruiter trust. Everyone who reads your README will check if you know the difference between a prototype and production.

---

## 8. Prioritized Action Plan

### Weekend 1 — ship the demo (≈6 hours)

1. **Fix bug 1.1** (`book_appointment` date/date shadowing) — 15 min, unblocks the demo
2. **Fix bug 1.2** (`datetime.utcnow` deprecation) — 15 min, 5 files, straightforward
3. **Fix bug 1.4** (duplicate atexit handler) — 5 min
4. **Rewrite the system prompt** (§2.1) — 1 hour, huge impact on feel
5. **Force acknowledgements on barge-in** (§2.2) — 45 min
6. **Delete SSML emotion tags** (§2.4) — 10 min
7. **Name-confirmation simplification** (§2.6) — 20 min, mostly deletion
8. **Add `## Status` paragraph to README** (§7.6) — 10 min
9. **Record demo and post** (§7.1, §7.2) — 2 hours

That's a fixable, impressive demo in a weekend.

### Weekend 2 — production-ish (≈8 hours)

10. **Fix race condition in booking** (§1.3) — 1 hour with tests
11. **Add 6-8 tests** (§6) — 2 hours
12. **Batch `check_availability` query** (§4.6) — 30 min
13. **PII redaction in logs** (§5.1) — 1 hour
14. **Health check that actually pings providers** (§4.5) — 30 min
15. **Inactivity timeout on calls** (§3.7) — 30 min
16. **Pre-recorded filler audio clips** (§2.5) — 2 hours — **best portfolio piece**

### Nice-to-have (for future posts)

17. Multi-provider failover (§3.1)
18. Circuit breaker (§3.3)
19. Per-caller auth + rate limiting (§5.2, §5.8)
20. sqlcipher encryption (§5.3)
21. Backchanneling (full impl from the stub)

---

## 9. Suggested Cursor Prompts

Copy-paste these into Cursor one at a time:

**Prompt 1 — fix the critical booking bug:**
> In `agent/tools/appointments.py`, the `book_appointment` function parameter `date: str` shadows the imported `date` class from datetime. The line `today = date.today()` raises AttributeError on a string. Rename the parameter to `appointment_date` throughout the function, then update the caller in `agent/tools/handlers.py:49-55` and the schema in `agent/tools/registry.py:26-38` to match.

**Prompt 2 — modernize datetime:**
> Replace every occurrence of `datetime.utcnow().isoformat() + "Z"` with `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`. Add `from datetime import timezone` where needed. Files: `agent/database/db.py`, `agent/database/repositories/callers.py`, `agent/services/reminders.py`, `agent/latency_tracker.py`.

**Prompt 3 — rewrite the system prompt:**
> Rewrite `agent/prompts.py`'s `get_system_prompt()` to be character-driven rather than a rule list. Keep today's date, clinic info, doctors, and the learn-from-feedback block. Replace the 16 ALL-CAPS rule sections with: (1) a 2-sentence persona, (2) two concrete example exchanges showing what good sounds like vs what bad sounds like, (3) 5-7 rules of thumb in plain language. Target 40% fewer tokens than the current version. Keep the booking flow guidance but phrase it as "Ask their name, confirm it, then on the next turn ask for phone" rather than numbered steps.

**Prompt 4 — acknowledgement on barge-in:**
> In `agent/barge_in_logger.py`, after an interruption is detected, set a flag on a shared context that the next LLM output should be prefixed with a randomly-chosen acknowledgement from ["Sure,", "Got it,", "Of course,", "No problem,"]. Implement by wrapping the LLM service to check the flag and prepend the token before the response. Clear the flag after one use.

**Prompt 5 — add tests:**
> Add pytest tests in `tests/test_appointments.py` for: (1) book_appointment happy path with in-memory SQLite, (2) check_availability when all slots are booked, (3) check_availability for an unknown doctor. Use a fixture that creates a temporary SQLite file and runs migrations.

---

## 10. What to Say on LinkedIn

Rough template:

> I built **Aria**, a voice-first AI receptionist for medical clinics. Talk to her in your browser — she books appointments, answers FAQs, recognizes returning callers, and escalates to human staff.
>
> The hardest part wasn't the voice. It was making her **feel human**.
>
> Voice agents feel robotic when: (a) the turn-taking latency is >500ms, (b) they never acknowledge interruptions, (c) they read tool results verbatim, (d) there's silence during tool calls. Aria tackles each:
>
> - Voice-to-voice latency p95 < 500ms. I instrument every stage (VAD, STT, LLM TTFT, TTS TTFB) and log per-turn breakdowns.
> - Pre-tool fillers ("let me check") so there's never silence.
> - A FunctionCallFilter processor that strips the LLM's function-call markup before TTS speaks it.
> - Dual-LLM routing: simple turns → gpt-4o-mini (fast), complex turns → gpt-4o (smart).
> - Emotion-aware TTS (well, I tried — and learned Cartesia's API wasn't the right place for this. Good lesson.)
> - **Learn from feedback**: every call's outcome gets distilled into a one-liner and injected into the next call's system prompt. Over time Aria avoids past mistakes.
>
> Stack: Pipecat + SmallWebRTC + Deepgram Nova-2 + OpenAI + Cartesia + SQLite.
>
> This is a **prototype**, not production-ready. For that you'd add: HIPAA-compliant encryption, per-caller auth, multi-provider failover, horizontal scaling with sticky sessions, real telephony (Twilio/SIP), and a ton of audit logging. Happy to talk through any of it.
>
> Code: [github link]
> Demo: [video/gif]

---

**Bottom line:** the project is a genuinely strong portfolio piece. Fix the critical booking bug, rewrite the prompt, record the demo, and ship it. The honest "what's missing for production" framing is what sets you apart — it shows judgment.
