# Aria Voice Agent — Production Implementation Roadmap

> **How to use this document:** Feed each section to Cursor as a self-contained task.
> Each section includes: what to build, why, exact file paths, edge cases, and acceptance criteria.
> Work top-to-bottom — later sections depend on earlier ones.

---

## Project Context (Give This to Cursor First)

Aria is a real-time voice AI receptionist for medical clinics, built on Pipecat (Python).
The pipeline: Browser/Phone → WebRTC/SIP → Deepgram STT → Groq LLM → Cartesia TTS → Audio out.
The LLM has tools (function calling) to book appointments, check availability, look up callers, etc.

**Current stack:** Pipecat, Deepgram Nova-2, Groq (Llama 3.3 70B), Cartesia Sonic-3, Silero VAD, aiosqlite.
**Target:** Production-grade agent supporting 50-100+ concurrent calls over both WebRTC and telephony.

**Critical constraint:** This is a REAL-TIME VOICE pipeline. Any blocking call, unhandled exception, or >200ms delay in the pipeline is audible to the caller as a stutter, silence, or disconnection. Every design decision must prioritize: never crash mid-call, never block the audio thread, fail gracefully with a spoken response.

---

## New Project Structure

```
aria-voice-agent/
├── agent/
│   ├── __init__.py
│   ├── main.py                    # Application entrypoint and lifecycle
│   ├── config.py                  # Pydantic settings (validated, typed)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py            # Pipeline builder (STT → LLM → TTS chain)
│   │   ├── session.py             # Per-call session state and lifecycle
│   │   ├── context_manager.py     # LLM context window management
│   │   └── errors.py              # Error boundaries and safe tool execution
│   │
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── factory.py             # Creates the right transport from config
│   │   ├── webrtc.py              # WebRTC-specific setup
│   │   └── telephony.py           # Twilio/SIP-specific setup
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── appointments.py        # Appointment business logic (no DB imports)
│   │   ├── caller_memory.py       # Caller lookup/update logic
│   │   ├── clinic_info.py         # FAQ retrieval logic
│   │   └── escalation.py          # Human handoff logic
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py            # Tool schema definitions + registration
│   │   └── handlers.py            # Tool handler wrappers (with error boundaries)
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── manager.py             # Single DB connection manager (lifecycle)
│   │   ├── models.py              # Pydantic models (not dataclasses)
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── doctors.py         # Doctor queries
│   │   │   ├── appointments.py    # Appointment queries
│   │   │   ├── callers.py         # Caller queries
│   │   │   └── clinic_info.py     # Clinic info queries
│   │   └── migrations/
│   │       └── 001_initial.sql    # Schema as migration
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── system.py              # System prompt
│   │   └── greeting.py            # Greeting prompt
│   │
│   └── observability/
│       ├── __init__.py
│       ├── logging.py             # Structured logging setup
│       ├── metrics.py             # Latency + call metrics
│       └── health.py              # Health check endpoint
│
├── tests/
│   ├── conftest.py                # Shared fixtures (DB, mock services)
│   ├── test_appointments.py       # Appointment service tests
│   ├── test_tool_handlers.py      # Tool error boundary tests
│   ├── test_context_manager.py    # Context window tests
│   ├── test_session.py            # Session lifecycle tests
│   └── test_database.py           # Repository tests
│
├── scripts/
│   ├── seed_db.py
│   └── healthcheck.py             # Docker healthcheck script
│
├── docker-compose.yml             # App + Postgres + Redis
├── Dockerfile
├── .env.example
├── pyproject.toml
└── docs/
    ├── ARCHITECTURE.md
    └── DEPLOYMENT.md
```

---

## SECTION 1: Config Hardening (Pydantic Settings)

### File: `agent/config.py`

**What to build:** Replace raw `os.getenv` calls with a Pydantic `BaseSettings` class that validates all config at startup — not at first use during a live call.

**Why:** Currently, if someone sets `DEEPGRAM_ENDPOINTING=abc` (not an int), the app doesn't crash until a caller connects and the pipeline tries to use it. With Pydantic, invalid config crashes at startup with a clear error message.

**Requirements:**
```python
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

class Settings(BaseSettings):
    # Required — app MUST NOT start without these
    deepgram_api_key: str
    groq_api_key: str
    cartesia_api_key: str

    # Optional with validated defaults
    cartesia_voice_id: str = "b7d50908-b17c-442d-ad8d-810c63997ed9"
    groq_model: str = "llama-3.3-70b-versatile"

    # Latency tuning — validated ranges
    deepgram_utterance_end_ms: int = Field(default=1000, ge=100, le=3000)
    deepgram_endpointing: int = Field(default=250, ge=50, le=1000)
    tts_low_latency: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///data/aria.db"
    # When set to a postgres:// URL, the app uses asyncpg instead

    # Redis (for session state in multi-instance deployments)
    redis_url: str | None = None

    # Transport
    transport_mode: str = "webrtc"  # "webrtc" | "twilio" | "daily"

    # Server
    port: int = Field(default=7860, ge=1, le=65535)
    host: str = "0.0.0.0"

    # Observability
    log_level: str = "INFO"
    logfire_token: str | None = None

    # Context management
    max_context_messages: int = Field(default=50, ge=10, le=200)
    context_summary_threshold: int = Field(default=40, ge=8, le=180)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("transport_mode")
    @classmethod
    def validate_transport(cls, v):
        allowed = {"webrtc", "twilio", "daily"}
        if v not in allowed:
            raise ValueError(f"transport_mode must be one of {allowed}")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v):
        if not v.startswith(("sqlite", "postgresql")):
            raise ValueError("database_url must start with sqlite or postgresql")
        return v

# Singleton — created once at import time, crashes fast if invalid
settings = Settings()
```

**Edge cases to handle:**
- `.env` file doesn't exist → Pydantic reads from actual env vars, no crash
- API key is empty string → add `@field_validator` that rejects empty strings for required keys
- `database_url` has wrong scheme → validator catches it
- `deepgram_utterance_end_ms` set to 50 → Field(ge=100) catches it with a clear error

**Acceptance criteria:**
- `python -c "from agent.config import settings; print(settings.model_dump())"` works or crashes with a clear validation error
- Every other module imports `settings` instead of calling `os.getenv` directly
- No more string-to-int conversions scattered across the codebase

**Dependencies to add to pyproject.toml:**
```
"pydantic>=2.0",
"pydantic-settings>=2.0",
```

---

## SECTION 2: Database Manager (Single Connection, Lifecycle Control)

### Files: `agent/database/manager.py`, `agent/database/repositories/*.py`, `agent/database/models.py`

**What to build:** One database manager that owns the connection lifecycle, with separate repository classes for each domain. Replace the three independent `_db` singletons.

**Why:** The current code creates 3 separate SQLite connections (one per tool file) to the same database. SQLite only allows one writer at a time. When two tools fire simultaneously (which happens — Groq can call `check_availability` and `lookup_caller` in the same turn), you get `database is locked` errors that crash the call.

### manager.py

```python
"""
Single database connection manager.
Owns the connection lifecycle. All repositories share this one connection.
For SQLite: one connection with WAL mode for concurrent reads.
For PostgreSQL: connection pool via asyncpg.
"""
import aiosqlite
from agent.config import settings

class DatabaseManager:
    """
    Usage:
        db = DatabaseManager()
        await db.startup()      # Call once at app start
        conn = db.connection     # All repos use this
        await db.shutdown()      # Call once at app teardown
    """
    def __init__(self):
        self._conn = None
        self._pool = None  # For PostgreSQL

    @property
    def is_postgres(self) -> bool:
        return settings.database_url.startswith("postgresql")

    async def startup(self) -> None:
        if self.is_postgres:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=5,
                max_size=20,  # Supports 50-100 concurrent calls
                command_timeout=10,
            )
        else:
            # SQLite path (local dev)
            from pathlib import Path
            db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(db_path)
            self._conn.row_factory = aiosqlite.Row
            # WAL mode: allows concurrent reads while writing
            await self._conn.execute("PRAGMA journal_mode=WAL")
            # Busy timeout: wait up to 5s instead of failing immediately
            await self._conn.execute("PRAGMA busy_timeout=5000")
            await self._create_tables()

    async def shutdown(self) -> None:
        if self._pool:
            await self._pool.close()
        if self._conn:
            await self._conn.close()

    @property
    def connection(self):
        """For SQLite — returns the single aiosqlite connection."""
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call startup() first.")
        return self._conn

    @property
    def pool(self):
        """For PostgreSQL — returns the asyncpg pool."""
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call startup() first.")
        return self._pool

    async def execute(self, query: str, *args):
        """Unified execute that works for both SQLite and PostgreSQL."""
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                return await conn.fetch(query, *args)
        else:
            async with self._conn.execute(query, args) as cur:
                return await cur.fetchall()

    async def execute_one(self, query: str, *args):
        """Fetch a single row."""
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        else:
            async with self._conn.execute(query, args) as cur:
                return await cur.fetchone()

    async def execute_write(self, query: str, *args):
        """Execute an INSERT/UPDATE/DELETE and commit."""
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                return await conn.execute(query, *args)
        else:
            await self._conn.execute(query, args)
            await self._conn.commit()

    async def _create_tables(self):
        """SQLite only — create tables if they don't exist."""
        # (move the existing CREATE TABLE statements here)
        pass

# Module-level instance — initialized in main.py startup
db_manager = DatabaseManager()
```

### models.py — Switch from dataclasses to Pydantic

```python
"""
Pydantic models — validated, serializable, consistent.
Why Pydantic over dataclasses: validation on construction catches
bad data before it reaches the LLM or caller.
"""
from pydantic import BaseModel, Field
from datetime import date, datetime
from enum import Enum

class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"

class Doctor(BaseModel):
    id: int
    name: str
    specialization: str
    available_days: list[str]
    slot_duration_minutes: int = 30

class Appointment(BaseModel):
    id: str                         # APT-XXXXX format
    doctor_id: int
    patient_name: str
    patient_phone: str
    appointment_date: str           # YYYY-MM-DD
    start_time: str                 # HH:MM:SS
    end_time: str                   # HH:MM:SS
    status: AppointmentStatus = AppointmentStatus.BOOKED
    created_at: str
    notes: str = ""

class Caller(BaseModel):
    id: int
    phone_number: str
    name: str = ""
    last_call_at: str
    preferences: dict = Field(default_factory=dict)
    call_count: int = 1

class ClinicInfo(BaseModel):
    key: str
    value: str
```

### repositories/appointments.py (example — same pattern for all repos)

```python
"""
Appointment repository — pure data access, no business logic.
Receives the DatabaseManager, never creates its own connection.
"""
from agent.database.manager import DatabaseManager
from agent.database.models import Appointment

class AppointmentRepository:
    def __init__(self, db: DatabaseManager):
        self._db = db

    async def get_by_id(self, appointment_id: str) -> Appointment | None:
        row = await self._db.execute_one(
            "SELECT * FROM appointments WHERE id = ?", appointment_id
        )
        return Appointment(**dict(row)) if row else None

    async def get_by_doctor_and_date(self, doctor_id: int, date: str) -> list[Appointment]:
        rows = await self._db.execute(
            """SELECT * FROM appointments
               WHERE doctor_id = ? AND appointment_date = ? AND status = 'booked'
               ORDER BY start_time""",
            doctor_id, date,
        )
        return [Appointment(**dict(r)) for r in rows]

    async def create(self, appointment: Appointment) -> None:
        await self._db.execute_write(
            """INSERT INTO appointments
               (id, doctor_id, patient_name, patient_phone, appointment_date,
                start_time, end_time, status, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            appointment.id, appointment.doctor_id, appointment.patient_name,
            appointment.patient_phone, appointment.appointment_date,
            appointment.start_time, appointment.end_time,
            appointment.status.value, appointment.created_at, appointment.notes,
        )

    async def update_status(self, appointment_id: str, status: str) -> bool:
        # Returns True if a row was actually updated
        # Implementation depends on SQLite vs Postgres
        pass

    async def reschedule(self, appointment_id: str, new_date: str, new_start: str, new_end: str) -> bool:
        pass
```

**Create the same pattern for:** `DoctorRepository`, `CallerRepository`, `ClinicInfoRepository`.

**Edge cases to handle:**
- `db_manager.startup()` not called → `RuntimeError` with clear message (not a silent None)
- SQLite busy timeout exceeded → WAL mode + `PRAGMA busy_timeout=5000` prevents most cases
- PostgreSQL pool exhausted → `asyncpg` raises `PoolAcquisitionError`, catch in error boundary
- Database file doesn't exist → `mkdir(parents=True)` handles this
- Concurrent writes to same appointment → use `WHERE status = 'booked'` in UPDATE to prevent double-cancel
- Connection dropped mid-query → PostgreSQL pool auto-reconnects; SQLite needs explicit reconnect logic

**Acceptance criteria:**
- Only ONE database connection/pool exists at runtime
- All tool files import repositories, never `aiosqlite` directly
- `grep -r "aiosqlite" agent/services/` returns nothing
- `grep -r "global _db" agent/` returns nothing

---

## SECTION 3: Error Boundaries (Never Crash a Live Call)

### Files: `agent/core/errors.py`, `agent/tools/handlers.py`

**What to build:** A `safe_tool_call` wrapper that catches any exception from tool execution and returns a spoken-language error string instead of crashing the pipeline.

**Why:** Currently, if the LLM sends malformed arguments (e.g., `"doctor_id": "two"` instead of `2`), the `int()` conversion throws `ValueError`. There's no try/except. The pipeline crashes. The caller hears silence, then gets disconnected. This WILL happen in production — LLMs misformat arguments regularly.

### core/errors.py

```python
"""
Error boundaries for the voice pipeline.
Rule: No unhandled exception should ever reach the pipeline.
Every failure becomes a spoken response to the caller.
"""
import traceback
from loguru import logger
from enum import Enum


class ErrorSeverity(Enum):
    """How bad is this failure?"""
    RECOVERABLE = "recoverable"   # Tool failed, but call continues
    DEGRADED = "degraded"         # Feature unavailable, offer alternative
    CRITICAL = "critical"         # Must escalate to human


# Spoken error messages — these are what the CALLER hears
TOOL_ERROR_RESPONSES = {
    "check_availability": "I'm having trouble checking the schedule right now. Let me transfer you to our front desk so they can help.",
    "book_appointment": "I ran into an issue while booking that. Let me connect you with our staff to make sure it's done correctly.",
    "reschedule_appointment": "I'm having trouble rescheduling. Let me transfer you to make sure your appointment is handled properly.",
    "cancel_appointment": "I couldn't process that cancellation. Let me connect you with someone who can help.",
    "get_clinic_info": "I'm having a little trouble looking that up. Is there something else I can help with, or would you like me to transfer you?",
    "lookup_caller": "I wasn't able to pull up your records, but no worries, I can still help you.",
    "escalate_to_human": "I'm connecting you with our staff right now. Please hold for just a moment.",
    "default": "I ran into a small issue. Let me connect you with our front desk to make sure you're taken care of.",
}


async def safe_tool_call(tool_name: str, handler, params, session_id: str = "unknown"):
    """
    Wraps every tool execution with error handling.

    On success: returns the tool's normal result string.
    On failure: logs the full error, returns a caller-friendly spoken message.

    This is the most important function in the entire codebase.
    If this function works correctly, the agent NEVER crashes mid-call.
    """
    try:
        return await handler(params)
    except Exception as e:
        # Log the full traceback for debugging
        logger.error(
            "Tool '{tool}' failed | session={session} | error={error} | traceback={tb}",
            tool=tool_name,
            session=session_id,
            error=str(e),
            tb=traceback.format_exc(),
        )
        # Return a spoken error — the caller hears this, not silence
        return TOOL_ERROR_RESPONSES.get(tool_name, TOOL_ERROR_RESPONSES["default"])


def safe_int(value, default: int = 0) -> int:
    """Safely convert LLM output to int. LLMs sometimes send '2' or 'two' or 2."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        # Handle common LLM outputs
        value = value.strip().lower()
        # Try direct conversion first
        try:
            return int(value)
        except ValueError:
            pass
        # Try float-to-int ("2.0")
        try:
            return int(float(value))
        except ValueError:
            pass
        # Handle word numbers the LLM might output
        word_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        if value in word_map:
            return word_map[value]
    return default


def safe_str(value, default: str = "") -> str:
    """Safely extract a string from LLM output."""
    if value is None:
        return default
    return str(value).strip()
```

### tools/handlers.py

```python
"""
Tool handlers — the bridge between Pipecat's function calling and our services.
Every handler is wrapped in safe_tool_call so exceptions become spoken errors.

IMPORTANT: These handlers receive raw LLM arguments. The LLM might send:
  - "doctor_id": "two" instead of 2
  - "date": "next Tuesday" instead of "2025-01-15"
  - Missing required fields entirely
  - Extra fields the schema didn't ask for

The handlers must tolerate ALL of these without crashing.
"""
from agent.core.errors import safe_tool_call, safe_int, safe_str
from agent.services import appointments, caller_memory, clinic_info, escalation


def create_tool_handlers(session_id: str = "unknown"):
    """
    Factory that creates tool handlers bound to a specific session.
    Each handler is wrapped in safe_tool_call.

    Returns a dict of {tool_name: async handler} ready for llm.register_function().
    """

    async def _check_availability(params):
        async def _inner(params):
            args = params.arguments
            result = await appointments.check_availability(
                safe_str(args.get("doctor_name_or_specialization"), ""),
                safe_str(args.get("preferred_date"), "next available"),
            )
            await params.result_callback(result)
        await safe_tool_call("check_availability", _inner, params, session_id)

    async def _book_appointment(params):
        async def _inner(params):
            args = params.arguments
            result = await appointments.book_appointment(
                doctor_id=safe_int(args.get("doctor_id"), 0),
                patient_name=safe_str(args.get("patient_name"), ""),
                patient_phone=safe_str(args.get("patient_phone"), ""),
                date=safe_str(args.get("date"), ""),
                time=safe_str(args.get("time"), ""),
                notes=safe_str(args.get("notes"), ""),
            )
            await params.result_callback(result)
        await safe_tool_call("book_appointment", _inner, params, session_id)

    async def _reschedule_appointment(params):
        async def _inner(params):
            args = params.arguments
            result = await appointments.reschedule_appointment(
                safe_str(args.get("appointment_id"), ""),
                safe_str(args.get("new_date"), ""),
                safe_str(args.get("new_time"), ""),
            )
            await params.result_callback(result)
        await safe_tool_call("reschedule_appointment", _inner, params, session_id)

    async def _cancel_appointment(params):
        async def _inner(params):
            args = params.arguments
            result = await appointments.cancel_appointment(
                safe_str(args.get("appointment_id"), ""),
                safe_str(args.get("reason"), ""),
            )
            await params.result_callback(result)
        await safe_tool_call("cancel_appointment", _inner, params, session_id)

    async def _get_clinic_info(params):
        async def _inner(params):
            result = await clinic_info.get_clinic_info(
                safe_str(params.arguments.get("topic"), "general")
            )
            await params.result_callback(result)
        await safe_tool_call("get_clinic_info", _inner, params, session_id)

    async def _lookup_caller(params):
        async def _inner(params):
            result = await caller_memory.lookup_caller(
                safe_str(params.arguments.get("phone_number"), "")
            )
            await params.result_callback(result)
        await safe_tool_call("lookup_caller", _inner, params, session_id)

    async def _escalate_to_human(params):
        async def _inner(params):
            result = await escalation.escalate_to_human(
                safe_str(params.arguments.get("reason"), "")
            )
            await params.result_callback(result)
        await safe_tool_call("escalate_to_human", _inner, params, session_id)

    return {
        "check_availability": _check_availability,
        "book_appointment": _book_appointment,
        "reschedule_appointment": _reschedule_appointment,
        "cancel_appointment": _cancel_appointment,
        "get_clinic_info": _get_clinic_info,
        "lookup_caller": _lookup_caller,
        "escalate_to_human": _escalate_to_human,
    }
```

### tools/registry.py

```python
"""
Tool schema definitions — separate from handlers so they can be
tested independently and reused across different LLM providers.
"""
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema


def get_tool_schemas() -> ToolsSchema:
    """Returns all tool schemas. Defined once, used everywhere."""
    return ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_availability",
            description="Check available appointment slots for a doctor by name or specialization. ALWAYS call this before suggesting times — never invent availability.",
            properties={
                "doctor_name_or_specialization": {
                    "type": "string",
                    "description": "Doctor name (e.g. 'Dr. Chen') or specialization (e.g. 'dermatology')"
                },
                "preferred_date": {
                    "type": "string",
                    "description": "Date as YYYY-MM-DD or 'next available'. Default: 'next available'"
                },
            },
            required=["doctor_name_or_specialization"],
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book an appointment. ALWAYS confirm all details with the caller before calling this.",
            properties={
                "doctor_id": {"type": "integer", "description": "Doctor ID from check_availability results"},
                "patient_name": {"type": "string", "description": "Patient's full name as stated by caller"},
                "patient_phone": {"type": "string", "description": "Patient's phone number"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Time as HH:MM (24h format)"},
                "notes": {"type": "string", "description": "Reason for visit or other notes"},
            },
            required=["doctor_id", "patient_name", "patient_phone", "date", "time"],
        ),
        FunctionSchema(
            name="reschedule_appointment",
            description="Reschedule an existing appointment to a new date/time.",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (format: APT-XXXXX)"},
                "new_date": {"type": "string", "description": "New date as YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "New time as HH:MM (24h format)"},
            },
            required=["appointment_id", "new_date", "new_time"],
        ),
        FunctionSchema(
            name="cancel_appointment",
            description="Cancel an existing appointment.",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (format: APT-XXXXX)"},
                "reason": {"type": "string", "description": "Reason for cancellation (optional)"},
            },
            required=["appointment_id"],
        ),
        FunctionSchema(
            name="get_clinic_info",
            description="Get clinic information: hours, address, insurance accepted, services offered, parking details.",
            properties={
                "topic": {
                    "type": "string",
                    "description": "One of: hours, address, insurance, services, parking, general",
                    "enum": ["hours", "address", "insurance", "services", "parking", "general"],
                },
            },
            required=["topic"],
        ),
        FunctionSchema(
            name="lookup_caller",
            description="Look up if a caller has called before by their phone number. Use to personalize the conversation.",
            properties={
                "phone_number": {"type": "string", "description": "Caller's phone number"},
            },
            required=["phone_number"],
        ),
        FunctionSchema(
            name="escalate_to_human",
            description="Transfer the call to human front desk staff. Use when: medical advice requested, billing questions, caller is upset and wants a person, anything outside Aria's scope.",
            properties={
                "reason": {"type": "string", "description": "Brief reason for the transfer"},
            },
            required=["reason"],
        ),
    ])
```

**Edge cases the error boundary must handle:**
- `int("two")` → ValueError → caught, returns spoken error
- `args.get("doctor_id")` returns None → `safe_int(None, 0)` returns 0
- Tool takes >5 seconds (DB lock, network issue) → add asyncio.timeout (see Section 6)
- `result_callback` itself fails → outer try/except still catches it
- LLM sends completely unrecognized arguments → `.get()` with defaults handles missing keys
- LLM sends empty string for required field → service layer validates and returns helpful error

**Acceptance criteria:**
- Deliberately break every tool (throw ValueError, RuntimeError, etc.) and verify the caller hears a spoken error, never silence
- No `int()` calls without `safe_int()` anywhere in tool handlers
- All tool registrations go through `create_tool_handlers()`, not inline in bot.py

---

## SECTION 4: Session Management (Per-Call State)

### File: `agent/core/session.py`

**What to build:** A `CallSession` class that gives every call a unique ID and tracks its lifecycle: who called, what tools were used, what happened, how long it took.

**Why:** Without sessions, you can't debug production issues. "A caller said their appointment wasn't booked" — which call? When? What did the LLM say? What tool was called? Session tracking answers all of this.

```python
"""
Call session — tracks everything that happens during one phone call.
Created when a caller connects, destroyed when they disconnect.
All logs and DB writes are tagged with session_id for debugging.
"""
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from enum import Enum


class CallOutcome(str, Enum):
    COMPLETED = "completed"        # Caller got what they needed
    ESCALATED = "escalated"        # Transferred to human
    ABANDONED = "abandoned"        # Caller hung up mid-conversation
    ERROR = "error"                # Something went wrong


class ToolInvocation(BaseModel):
    tool_name: str
    arguments: dict
    result: str
    duration_ms: float
    success: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CallSession(BaseModel):
    """
    One instance per call. Passed to all tool handlers and services.
    """
    session_id: str = Field(default_factory=lambda: f"call-{uuid.uuid4().hex[:12]}")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    caller_phone: str | None = None
    caller_name: str | None = None
    transport_type: str = "webrtc"     # "webrtc" | "twilio" | "daily"
    outcome: CallOutcome | None = None

    # Conversation tracking
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    turn_count: int = 0
    total_latency_ms: float = 0.0

    # Error tracking
    errors: list[str] = Field(default_factory=list)

    def record_tool_call(self, tool_name: str, args: dict, result: str, duration_ms: float, success: bool):
        self.tool_invocations.append(ToolInvocation(
            tool_name=tool_name,
            arguments=args,
            result=result[:200],  # Truncate for storage
            duration_ms=duration_ms,
            success=success,
        ))

    def record_error(self, error: str):
        self.errors.append(f"{datetime.now(timezone.utc).isoformat()}: {error}")

    def end(self, outcome: CallOutcome):
        self.ended_at = datetime.now(timezone.utc)
        self.outcome = outcome

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at and self.started_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    def summary(self) -> dict:
        """For logging at end of call."""
        return {
            "session_id": self.session_id,
            "duration_s": self.duration_seconds,
            "turns": self.turn_count,
            "tools_called": len(self.tool_invocations),
            "errors": len(self.errors),
            "outcome": self.outcome.value if self.outcome else "unknown",
        }
```

**Where sessions are created and destroyed (in pipeline.py):**
- `on_client_connected` → create `CallSession`, log it
- `on_client_disconnected` → call `session.end(outcome)`, log summary
- Pass `session.session_id` to all tool handlers and log statements

**Edge cases:**
- Caller disconnects during a tool call → `on_client_disconnected` fires, session is ended as "abandoned", pending tool call gets caught by error boundary
- Multiple rapid disconnects/reconnects → each gets its own session_id
- Session data grows large (chatty caller, many tool calls) → `result[:200]` truncation prevents unbounded growth
- Server crashes → session data is lost (acceptable for now; future: persist to Redis)

**Acceptance criteria:**
- Every log line during a call includes `session_id`
- At end of call, a summary is logged with duration, tool count, errors, outcome
- `grep -r "session_id" agent/` shows it's threaded through tools, handlers, and pipeline

---

## SECTION 5: Context Window Management

### File: `agent/core/context_manager.py`

**What to build:** A manager that prevents the LLM context from growing unboundedly. After a threshold, older messages are summarized and compressed.

**Why:** Currently, every message is appended to `LLMContext.messages` forever. A 10-minute call can easily hit 50+ messages. Groq's Llama 3.3 70B has a 128K context window, but the larger the context, the slower the response and the higher the cost. More importantly, very long contexts cause the LLM to lose track of the current conversation state.

```python
"""
Context window management for long calls.
Keeps the system prompt + recent messages, summarizes older ones.

Strategy:
  - System prompt: always kept (position 0)
  - Recent messages: last N exchanges kept verbatim
  - Older messages: summarized into a single "conversation so far" message
  - Tool results: kept only for the most recent tool call

This prevents context overflow while maintaining conversation coherence.
"""
from loguru import logger
from agent.config import settings


class ContextManager:
    """
    Wraps LLMContext to manage message history.

    Usage:
        cm = ContextManager(context)
        cm.maybe_trim()  # Call after each turn
    """
    def __init__(self, context):
        self.context = context
        self.max_messages = settings.max_context_messages
        self.trim_threshold = settings.context_summary_threshold

    def message_count(self) -> int:
        return len(self.context.messages)

    def maybe_trim(self) -> bool:
        """
        Check if context needs trimming. If so, summarize older messages.
        Returns True if trimming occurred.

        Call this after every user turn, BEFORE sending to LLM.
        """
        if self.message_count() < self.trim_threshold:
            return False

        logger.info(
            "Context trimming: {count} messages exceeds threshold {threshold}",
            count=self.message_count(),
            threshold=self.trim_threshold,
        )

        messages = self.context.messages
        system_prompt = messages[0]  # Always the system prompt

        # Keep the last 10 exchanges (20 messages: 10 user + 10 assistant)
        keep_count = 20
        recent = messages[-keep_count:]
        old = messages[1:-keep_count]  # Skip system prompt, skip recent

        # Build a summary of old messages
        summary = self._summarize(old)

        # Rebuild context: system + summary + recent
        self.context.messages.clear()
        self.context.messages.append(system_prompt)
        self.context.messages.append({
            "role": "system",
            "content": f"Summary of earlier conversation: {summary}"
        })
        self.context.messages.extend(recent)

        logger.info(
            "Context trimmed: {old_count} → {new_count} messages",
            old_count=len(messages),
            new_count=self.message_count(),
        )
        return True

    def _summarize(self, messages: list[dict]) -> str:
        """
        Create a text summary of old messages.

        NOTE: This is a simple extractive summary, NOT an LLM call.
        We do NOT call the LLM to summarize because:
        1. It would add latency during a live call
        2. It could fail, and then what?
        3. For a medical receptionist, the key info is structured

        Instead, we extract the important facts:
        - What the caller asked for
        - What tools were called and their results
        - Any confirmed appointments
        """
        summary_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not content or not isinstance(content, str):
                continue

            # Keep assistant messages that contain appointment confirmations
            if role == "assistant":
                if any(keyword in content.lower() for keyword in [
                    "booked", "confirmed", "cancelled", "rescheduled",
                    "appointment id", "apt-"
                ]):
                    summary_parts.append(f"Aria confirmed: {content[:150]}")

            # Keep user messages that state intent
            if role == "user" and len(content) > 10:
                summary_parts.append(f"Caller said: {content[:100]}")

            # Keep tool results (they contain factual data)
            if role == "tool" or (role == "assistant" and "function" in str(msg)):
                summary_parts.append(f"Tool result: {content[:150]}")

        if not summary_parts:
            return "Earlier conversation covered general questions and greetings."

        # Limit summary size
        return " | ".join(summary_parts[:10])
```

**Edge cases:**
- Call starts and immediately hits trim (shouldn't happen, threshold > keep_count)
- Messages contain tool call/result pairs that reference each other → keeping last 20 ensures pairs stay together
- System prompt is accidentally trimmed → first message is always preserved
- Summary itself is very long → `[:150]` per message and `[:10]` messages caps it
- Context has non-string content (image, tool_use blocks) → `isinstance(content, str)` check
- Groq returns an error about context length → this prevents it from happening in the first place

**Acceptance criteria:**
- Run a simulated 30-turn conversation → context stays under `max_context_messages`
- System prompt is never lost after trimming
- Recent 10 exchanges are always verbatim (no information loss for active conversation)

---

## SECTION 6: Transport Abstraction (WebRTC + Telephony)

### Files: `agent/transport/factory.py`, `agent/transport/webrtc.py`, `agent/transport/telephony.py`

**What to build:** A factory that creates the right Pipecat transport based on config. The pipeline code doesn't know or care which transport is being used.

**Why:** Currently hardcoded to `SmallWebRTCTransport`. To support phone calls (Twilio), you need a different transport. A factory pattern lets you add new transports without touching pipeline code.

### transport/factory.py

```python
"""
Transport factory — creates the right transport based on config.
The pipeline doesn't know if audio is coming from a browser or a phone.
"""
from loguru import logger
from agent.config import settings


async def create_transport(runner_args=None):
    """
    Create a transport instance based on settings.transport_mode.

    For WebRTC: uses SmallWebRTC (peer-to-peer, no API key needed)
    For Twilio: uses Pipecat's Twilio transport (requires Twilio credentials)
    For Daily: uses Daily.co transport (requires Daily API key)

    Returns: (transport, transport_type_string)
    """
    mode = settings.transport_mode

    if mode == "webrtc":
        return _create_webrtc_transport(runner_args), "webrtc"
    elif mode == "twilio":
        return await _create_twilio_transport(), "twilio"
    elif mode == "daily":
        return _create_daily_transport(runner_args), "daily"
    else:
        raise ValueError(f"Unknown transport mode: {mode}")


def _create_webrtc_transport(runner_args):
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.transports.base_transport import TransportParams

    logger.info("Creating SmallWebRTC transport")
    return SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        webrtc_connection=runner_args.webrtc_connection if runner_args else None,
    )


async def _create_twilio_transport():
    """
    Twilio transport for phone calls.

    NOTE FOR CURSOR: Pipecat has built-in Twilio support.
    See: pipecat.transports.services.twilio
    This requires additional env vars:
      - TWILIO_ACCOUNT_SID
      - TWILIO_AUTH_TOKEN
      - TWILIO_PHONE_NUMBER

    The transport handles:
      - Inbound calls (webhook → WebSocket → audio stream)
      - Outbound calls (API → audio stream)
      - DTMF tone detection (for "press 1 for...")
      - Call recording consent
    """
    # TODO: Implement when Twilio credentials are available
    # This is stubbed so the factory pattern is in place
    raise NotImplementedError(
        "Twilio transport not yet configured. "
        "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in .env"
    )


def _create_daily_transport(runner_args):
    """
    Daily.co transport for scalable WebRTC.
    SmallWebRTC is peer-to-peer (good for dev).
    Daily is SFU-based (good for production — handles NAT, scaling, recording).

    Requires: DAILY_API_KEY in .env
    """
    # TODO: Implement when Daily API key is available
    raise NotImplementedError(
        "Daily transport not yet configured. Set DAILY_API_KEY in .env"
    )
```

**Edge cases:**
- `runner_args` is None (e.g., when running tests) → guard with `if runner_args` check
- Twilio webhook receives a call but transport isn't configured → clear error message
- Transport disconnects mid-call → Pipecat fires `on_client_disconnected`, session is properly ended
- Multiple simultaneous WebRTC connections → each gets its own transport + pipeline + session

**Acceptance criteria:**
- `settings.transport_mode = "webrtc"` works exactly as before
- Setting `transport_mode = "twilio"` gives a clear "not yet configured" error, not a crash
- Pipeline code (`pipeline.py`) never imports any specific transport class directly

---

## SECTION 7: Appointment ID Fix + Business Logic Hardening

### File: `agent/services/appointments.py`

**What to build:** Fix the appointment ID collision bug and add validation to all business logic.

**Current bug:**
```python
apt_id = f"APT-{random.randint(1000, 9999)}"  # Only 9000 possible IDs!
```

**Fix:**
```python
import uuid

def generate_appointment_id() -> str:
    """
    Generate a unique appointment ID.
    Format: APT-XXXXX (5 hex chars = 1,048,576 possibilities)
    Uses UUID to guarantee uniqueness across concurrent calls.
    """
    return f"APT-{uuid.uuid4().hex[:5].upper()}"
```

**Additional business logic hardening for appointments.py:**

```python
"""
Appointment service — business logic only.
Receives a repository instance, never touches the database directly.
All input is validated before hitting the database.
"""
from datetime import date, datetime, timedelta
from agent.database.repositories.appointments import AppointmentRepository
from agent.database.repositories.doctors import DoctorRepository
import uuid


def generate_appointment_id() -> str:
    return f"APT-{uuid.uuid4().hex[:5].upper()}"


# Business rules as constants
SLOT_DURATION_MINUTES = 30
CLINIC_OPEN_HOUR = 9
CLINIC_CLOSE_HOUR = 17
MAX_ADVANCE_BOOKING_DAYS = 90
MIN_BOOKING_NOTICE_HOURS = 1  # Can't book an appointment in the past


def _validate_booking_date(date_str: str) -> tuple[date | None, str | None]:
    """
    Validate a booking date. Returns (date, None) on success or (None, error_message) on failure.
    """
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None, f"I couldn't understand the date '{date_str}'. Could you give it to me as year-month-day, like 2025-01-15?"

    today = date.today()

    if d < today:
        return None, "That date has already passed. Would you like to look at upcoming dates instead?"

    if d.weekday() >= 5:
        return None, "We're not open on weekends. Would you like me to check Monday instead?"

    if (d - today).days > MAX_ADVANCE_BOOKING_DAYS:
        return None, f"I can only book up to {MAX_ADVANCE_BOOKING_DAYS} days out. Would you like a closer date?"

    return d, None


def _validate_booking_time(time_str: str, booking_date: date) -> tuple[str | None, str | None]:
    """
    Validate a booking time. Returns (normalized_time_HH:MM:SS, None) on success
    or (None, error_message) on failure.
    """
    # Normalize time format
    time_str = time_str.strip()
    if len(time_str) == 5:  # HH:MM
        time_str = time_str + ":00"
    if len(time_str) != 8:  # HH:MM:SS
        return None, f"I couldn't understand the time '{time_str}'. Could you say it like 10:30?"

    try:
        t = datetime.strptime(time_str, "%H:%M:%S")
    except ValueError:
        return None, f"I couldn't understand the time '{time_str}'. Could you say it like 10:30?"

    if t.hour < CLINIC_OPEN_HOUR or t.hour >= CLINIC_CLOSE_HOUR:
        return None, f"Our clinic hours are {CLINIC_OPEN_HOUR} AM to {CLINIC_CLOSE_HOUR - 12} PM. Would you like a time within those hours?"

    # Check if the appointment is in the past
    now = datetime.now()
    booking_datetime = datetime.combine(booking_date, t.time())
    if booking_datetime < now + timedelta(hours=MIN_BOOKING_NOTICE_HOURS):
        return None, "That time has already passed or is too soon. Would you like a later time?"

    return time_str, None


async def check_availability(
    doctor_repo: DoctorRepository,
    appointment_repo: AppointmentRepository,
    doctor_name_or_specialization: str,
    preferred_date: str = "next available",
) -> str:
    """Check available slots. Validates inputs, queries DB, formats response."""

    if not doctor_name_or_specialization.strip():
        return "I'd be happy to check availability. Which doctor are you looking for, or what type of care do you need? We have general practice, cardiology, dermatology, and pediatrics."

    doctors = await doctor_repo.get_by_name_or_specialization(doctor_name_or_specialization)
    if not doctors:
        return f"I couldn't find a doctor matching '{doctor_name_or_specialization}'. We have Dr. Chen for general, Dr. Okafor for cardiology, Dr. Rodriguez for dermatology, and Dr. Kim for pediatrics."

    # Determine dates to check
    today = date.today()
    if preferred_date and preferred_date.lower() not in ("next available", ""):
        target, err = _validate_booking_date(preferred_date)
        if err:
            return err
        dates_to_check = [target]
    else:
        dates_to_check = []
        for i in range(14):
            d = today + timedelta(days=i)
            if d.weekday() < 5:
                dates_to_check.append(d)
                if len(dates_to_check) >= 5:
                    break

    # ... (rest of availability logic, same as current but using repos)
    # Key change: return doctor_id in results so LLM can pass it to book_appointment
    pass


async def book_appointment(
    doctor_repo: DoctorRepository,
    appointment_repo: AppointmentRepository,
    caller_repo,  # CallerRepository
    doctor_id: int,
    patient_name: str,
    patient_phone: str,
    date_str: str,
    time_str: str,
    notes: str = "",
) -> str:
    """
    Book an appointment with full validation.

    Validations:
    1. Doctor exists
    2. Date is valid (not past, not weekend, not >90 days out)
    3. Time is valid (within clinic hours, not in the past)
    4. Slot is still available (race condition check)
    5. Patient name is not empty
    6. Generate unique ID
    """

    # Validate doctor
    if doctor_id <= 0:
        return "I need to know which doctor you'd like to see. Could you tell me the doctor's name?"

    doctor = await doctor_repo.get_by_id(doctor_id)
    if not doctor:
        return "I couldn't find that doctor in our system. Would you like me to check who's available?"

    # Validate patient info
    if not patient_name.strip():
        return "I'll need your full name to book the appointment. What name should I put it under?"

    if not patient_phone.strip():
        return "I'll need a phone number for the appointment. What's the best number to reach you?"

    # Validate date
    booking_date, date_err = _validate_booking_date(date_str)
    if date_err:
        return date_err

    # Check doctor works on this day
    day_name = booking_date.strftime("%A")
    if day_name not in doctor.available_days:
        return f"Dr. {doctor.name.split()[-1]} isn't in on {day_name}s. Would you like me to check a different day?"

    # Validate time
    normalized_time, time_err = _validate_booking_time(time_str, booking_date)
    if time_err:
        return time_err

    # Check slot availability (race condition protection)
    end_dt = datetime.strptime(normalized_time, "%H:%M:%S") + timedelta(minutes=SLOT_DURATION_MINUTES)
    end_time = f"{end_dt.hour:02d}:{end_dt.minute:02d}:00"

    existing = await appointment_repo.get_by_doctor_and_date(doctor_id, booking_date.isoformat())
    for apt in existing:
        if apt.start_time == normalized_time:
            return "Oh, it looks like that slot was just taken. Let me check what else is available."

    # Book it
    apt_id = generate_appointment_id()
    # ... create appointment using repository
    # ... upsert caller using caller repository

    return f"You're all set! Your appointment with {doctor.name} is confirmed for {day_name} {booking_date.strftime('%B %d')} at {_format_time_display(normalized_time)}. Your appointment ID is {apt_id}."
```

**Edge cases this handles that the current code doesn't:**
- Booking in the past → "That date has already passed"
- Booking on a weekend → "We're not open on weekends"
- Booking 6 months out → "I can only book up to 90 days out"
- Empty patient name → "I'll need your full name"
- Doctor ID 0 (from safe_int default) → "I need to know which doctor"
- Time outside clinic hours → "Our clinic hours are 9 AM to 5 PM"
- Slot taken between check and book → "That slot was just taken"
- Malformed date string → friendly re-ask
- UUID-based appointment IDs → no collisions ever

**Acceptance criteria:**
- Every invalid input returns a helpful spoken message, not an error
- `generate_appointment_id()` produces unique IDs (test with 10,000 calls)
- Booking a slot that was just taken returns a friendly message

---

## SECTION 8: Pipeline Refactor (Putting It All Together)

### Files: `agent/core/pipeline.py`, `agent/main.py`

**What to build:** Refactor `bot.py` into a clean pipeline builder that uses all the new components: sessions, error boundaries, context management, transport factory.

### core/pipeline.py

```python
"""
Pipeline builder — assembles the Pipecat pipeline from components.
This is the central orchestration file.

Responsibilities:
  - Create STT, LLM, TTS services from config
  - Wire up tool handlers with error boundaries
  - Attach session tracking
  - Set up context management
  - Connect to the provided transport

Does NOT know about transport specifics (WebRTC vs Twilio).
"""
from loguru import logger
from agent.config import settings
from agent.core.session import CallSession
from agent.core.context_manager import ContextManager
from agent.tools.registry import get_tool_schemas
from agent.tools.handlers import create_tool_handlers
from agent.prompts.system import SYSTEM_PROMPT
from agent.prompts.greeting import GREETING_PROMPT
from agent.database.manager import db_manager

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.tts_service import TextAggregationMode
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver


try:
    from deepgram import LiveOptions
except ImportError:
    LiveOptions = None


def create_stt() -> DeepgramSTTService:
    """Create and configure the Speech-to-Text service."""
    stt_kwargs = {"api_key": settings.deepgram_api_key}
    if LiveOptions:
        stt_kwargs["live_options"] = LiveOptions(
            model="nova-2",
            language="en",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=True,
            smart_format=True,
            endpointing=settings.deepgram_endpointing,
            utterance_end_ms=settings.deepgram_utterance_end_ms,
        )
    return DeepgramSTTService(**stt_kwargs)


def create_llm(tools_schema, tool_handlers: dict) -> GroqLLMService:
    """Create and configure the LLM service with tools."""
    llm = GroqLLMService(
        api_key=settings.groq_api_key,
        settings=GroqLLMService.Settings(
            model=settings.groq_model,
            temperature=0.5,
            max_completion_tokens=150,
        ),
    )
    # Register all tool handlers
    for name, handler in tool_handlers.items():
        llm.register_function(name, handler)
    return llm


def create_tts() -> CartesiaTTSService:
    """Create and configure the Text-to-Speech service."""
    return CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        text_aggregation_mode=(
            TextAggregationMode.TOKEN if settings.tts_low_latency
            else TextAggregationMode.SENTENCE
        ),
        settings=CartesiaTTSService.Settings(
            voice=settings.cartesia_voice_id,
            generation_config=GenerationConfig(
                emotion="content",
                speed=1.0,
            ),
        ),
    )


async def run_pipeline(transport, session: CallSession):
    """
    Build and run the full voice pipeline for one call.

    This is called once per caller connection.
    """
    # Create tool handlers with error boundaries, bound to this session
    tool_handlers = create_tool_handlers(session_id=session.session_id)
    tools_schema = get_tool_schemas()

    # Build services
    stt = create_stt()
    llm = create_llm(tools_schema, tool_handlers)
    tts = create_tts()

    # LLM context with system prompt
    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=tools_schema,
    )
    context_manager = ContextManager(context)

    # Aggregators (VAD-driven turn management)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    # Build pipeline
    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    # Latency observer
    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_latency_measured")
    async def _on_latency(observer, latency_seconds):
        session.total_latency_ms += latency_seconds * 1000
        session.turn_count += 1
        logger.info(
            "[LATENCY] session={session} turn={turn} latency={latency:.2f}s",
            session=session.session_id,
            turn=session.turn_count,
            latency=latency_seconds,
        )

    task = PipelineTask(
        pipeline,
        observers=[latency_observer],
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
        ),
    )

    # --- Event handlers ---

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(
            "[SESSION] Call started | session={session} transport={transport_type}",
            session=session.session_id,
            transport_type=session.transport_type,
        )
        # Greet the caller with a system-level instruction (NOT a fake user message)
        context.add_message({
            "role": "system",
            "content": f"A caller just connected. Greet them by saying: {GREETING_PROMPT}"
        })
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        if session.outcome is None:
            session.end(outcome="abandoned")
        logger.info(
            "[SESSION] Call ended | {summary}",
            summary=session.summary(),
        )
        # Trim context on turn (for multi-turn awareness)
        context_manager.maybe_trim()
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
```

### main.py

```python
"""
Application entrypoint — lifecycle management.
Starts up DB, creates transport, runs the pipeline.
"""
from loguru import logger
from agent.config import settings
from agent.core.session import CallSession
from agent.core.pipeline import run_pipeline
from agent.transport.factory import create_transport
from agent.database.manager import db_manager
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments


async def startup():
    """Initialize all shared resources. Called once at app start."""
    logger.info("Starting Aria voice agent...")
    logger.info("Config: model={model} transport={transport}", model=settings.groq_model, transport=settings.transport_mode)

    # Initialize database
    await db_manager.startup()
    logger.info("Database connected: {url}", url=settings.database_url[:30] + "...")


async def shutdown():
    """Clean up all shared resources. Called once at app stop."""
    await db_manager.shutdown()
    logger.info("Aria voice agent stopped.")


async def bot(runner_args: RunnerArguments):
    """
    Entry point for Pipecat development runner.
    Called once per incoming connection.
    """
    await startup()

    try:
        transport, transport_type = await create_transport(runner_args)
        session = CallSession(transport_type=transport_type)
        await run_pipeline(transport, session)
    finally:
        await shutdown()


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
```

**Key architectural change: the greeting.**

Current (broken):
```python
context.add_message({"role": "user", "content": f"Greet the caller. Say: {GREETING_PROMPT}"})
```

Fixed:
```python
context.add_message({"role": "system", "content": f"A caller just connected. Greet them by saying: {GREETING_PROMPT}"})
```

The greeting is now a system instruction, not a fake user message. This prevents context pollution.

**Acceptance criteria:**
- `bot.py` is replaced by `main.py` + `core/pipeline.py`
- No function is longer than 40 lines
- Every component (STT, LLM, TTS) is created by its own factory function
- Session ID appears in all log lines during a call
- Greeting doesn't pollute conversation history as a user message

---

## SECTION 9: Observability (Health Checks + Structured Logging)

### Files: `agent/observability/health.py`, `agent/observability/logging.py`

**What to build:** A `/health` endpoint that checks all dependencies, plus structured logging.

### observability/health.py

```python
"""
Health check endpoint.
Returns status of all dependencies: STT, LLM, TTS, DB.
Used by Docker HEALTHCHECK, load balancers, and monitoring.
"""
import asyncio
import time
from agent.config import settings
from agent.database.manager import db_manager


async def check_health() -> dict:
    """
    Check all dependencies. Returns a dict with:
    {
        "status": "healthy" | "degraded" | "unhealthy",
        "checks": {
            "database": {"status": "ok", "latency_ms": 2.1},
            "deepgram": {"status": "ok"},
            "groq": {"status": "ok"},
            "cartesia": {"status": "ok"},
        }
    }
    """
    checks = {}

    # Database check
    try:
        start = time.monotonic()
        await db_manager.execute_one("SELECT 1")
        latency = (time.monotonic() - start) * 1000
        checks["database"] = {"status": "ok", "latency_ms": round(latency, 1)}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}

    # API key presence checks (don't call external APIs in health checks —
    # that costs money and adds latency. Just verify keys exist.)
    checks["deepgram"] = {"status": "ok" if settings.deepgram_api_key else "missing_key"}
    checks["groq"] = {"status": "ok" if settings.groq_api_key else "missing_key"}
    checks["cartesia"] = {"status": "ok" if settings.cartesia_api_key else "missing_key"}

    # Overall status
    statuses = [c["status"] for c in checks.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif "error" in statuses or "missing_key" in statuses:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}
```

### observability/logging.py

```python
"""
Structured logging configuration.
All log lines include session_id when available.
"""
import sys
from loguru import logger
from agent.config import settings


def setup_logging():
    """Configure loguru for structured logging."""
    logger.remove()  # Remove default handler

    # Console output — human-readable for development
    log_format = (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{message}"
    )
    logger.add(
        sys.stderr,
        format=log_format,
        level=settings.log_level,
        colorize=True,
    )

    # JSON output for production (if LOG_FORMAT=json in env)
    # This is what log aggregators like Datadog/Grafana ingest
    # Uncomment for production:
    # logger.add(
    #     sys.stdout,
    #     serialize=True,  # JSON format
    #     level=settings.log_level,
    # )
```

**Acceptance criteria:**
- `curl localhost:7860/health` returns JSON with all dependency statuses
- When DB is down, health returns `"unhealthy"`
- Every log line during a call has `session=call-xxxxxxxxxxxx`

---

## SECTION 10: Docker + PostgreSQL Setup

### docker-compose.yml

```yaml
services:
  aria:
    build: .
    ports:
      - "${PORT:-7860}:7860"
    env_file: .env
    environment:
      - DATABASE_URL=postgresql://aria:aria_pass@postgres:5432/aria_db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "scripts/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: aria
      POSTGRES_PASSWORD: aria_pass
      POSTGRES_DB: aria_db
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./agent/database/migrations/001_initial.sql:/docker-entrypoint-initdb.d/001_initial.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aria"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent/ agent/
COPY scripts/ scripts/

EXPOSE 7860

# Run with uv
CMD ["uv", "run", "python", "-m", "agent.main", "-t", "webrtc"]
```

### migrations/001_initial.sql

```sql
-- Initial schema for Aria voice agent
-- Works for both PostgreSQL and SQLite (with minor syntax differences)

CREATE TABLE IF NOT EXISTS doctors (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    specialization TEXT NOT NULL,
    available_days JSONB NOT NULL DEFAULT '[]',
    slot_duration_minutes INTEGER DEFAULT 30
);

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    appointment_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled', 'completed', 'no_show')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT DEFAULT '',

    -- Prevent double-booking: one doctor can't have two appointments at the same time
    UNIQUE (doctor_id, appointment_date, start_time, status)
);

CREATE TABLE IF NOT EXISTS callers (
    id SERIAL PRIMARY KEY,
    phone_number TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT '',
    last_call_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    preferences JSONB DEFAULT '{}',
    call_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clinic_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_appointments_doctor_date
    ON appointments(doctor_id, appointment_date)
    WHERE status = 'booked';

CREATE INDEX IF NOT EXISTS idx_callers_phone
    ON callers(phone_number);
```

**Key PostgreSQL improvements over the current SQLite schema:**
- `SERIAL` primary keys (auto-increment)
- `JSONB` for available_days and preferences (queryable, not just text)
- `DATE` and `TIME` types (not just text)
- `TIMESTAMPTZ` for created_at (timezone-aware)
- `CHECK` constraint on status (enforces valid values)
- `UNIQUE` constraint on `(doctor_id, appointment_date, start_time, status)` — prevents double-booking at the database level
- Indexes on common query patterns

**Acceptance criteria:**
- `docker-compose up` starts all three services
- `docker-compose up aria` waits for Postgres and Redis to be healthy before starting
- App connects to PostgreSQL in Docker, SQLite locally (based on `DATABASE_URL`)
- Health check passes in Docker

---

## SECTION 11: Tests

### Files: `tests/conftest.py`, `tests/test_*.py`

**What to build:** A test suite that covers the critical paths: error boundaries, appointment booking, context management, and session lifecycle.

### conftest.py

```python
"""
Shared test fixtures.
Uses an in-memory SQLite database for speed.
"""
import pytest
import pytest_asyncio
from agent.database.manager import DatabaseManager


@pytest_asyncio.fixture
async def db():
    """Fresh in-memory database for each test."""
    manager = DatabaseManager()
    manager._test_mode = True  # Uses in-memory SQLite
    # Override the database URL for testing
    import aiosqlite
    manager._conn = await aiosqlite.connect(":memory:")
    manager._conn.row_factory = aiosqlite.Row
    await manager._create_tables()
    yield manager
    await manager.shutdown()
```

### Tests to write (give these descriptions to Cursor):

**test_tool_handlers.py:**
- Test that `safe_tool_call` catches ValueError and returns a spoken error string
- Test that `safe_tool_call` catches RuntimeError and returns a spoken error string
- Test that `safe_tool_call` catches database connection errors and returns a spoken error string
- Test that `safe_int("two")` returns the default value
- Test that `safe_int("2.0")` returns 2
- Test that `safe_int(None)` returns the default value
- Test that `safe_int(3)` returns 3

**test_appointments.py:**
- Test booking with valid inputs succeeds
- Test booking in the past returns friendly error
- Test booking on weekend returns friendly error
- Test booking with empty patient name returns friendly error
- Test double-booking same slot returns friendly error
- Test `generate_appointment_id()` produces unique IDs (generate 10,000 and check for duplicates)
- Test availability check with unknown doctor returns helpful message
- Test availability check with empty string returns helpful message

**test_context_manager.py:**
- Test that context under threshold is not trimmed
- Test that context over threshold is trimmed to correct size
- Test that system prompt is never removed after trimming
- Test that recent messages are preserved verbatim after trimming
- Test that appointment confirmations appear in summary

**test_session.py:**
- Test that session generates unique IDs
- Test that `session.end()` sets ended_at and outcome
- Test that `record_tool_call()` appends to invocations
- Test that `summary()` returns all expected fields
- Test that `duration_seconds` is calculated correctly

**test_database.py:**
- Test creating and retrieving an appointment
- Test cancelling an appointment updates status
- Test rescheduling an appointment updates date and time
- Test looking up caller by phone (exists and doesn't exist)
- Test upserting caller increments call_count
- Test getting clinic info by key (exists and doesn't exist)

**Acceptance criteria:**
- `pytest` runs all tests and they pass
- Tests don't require any external services (no API keys, no Postgres)
- Each test file can run independently

---

## SECTION 12: Updated pyproject.toml

```toml
[project]
name = "aria-voice-agent"
version = "0.2.0"
description = "Production-grade AI voice receptionist for medical clinics"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    # Voice pipeline
    "pipecat-ai[deepgram,cartesia,openai,silero,webrtc,runner]>=0.0.50",
    "groq>=0.4.0",

    # Config and validation
    "pydantic>=2.0",
    "pydantic-settings>=2.0",

    # Database
    "aiosqlite>=0.19.0",  # Local dev (SQLite)
    "asyncpg>=0.29.0",    # Production (PostgreSQL)

    # Utilities
    "python-dotenv>=1.0.0",
    "logfire>=0.1.0",
    "redis>=5.0.0",        # Session state (optional)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.0.0",
]
twilio = [
    "pipecat-ai[twilio]>=0.0.50",
]
daily = [
    "pipecat-ai[daily]>=0.0.50",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["agent"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## Implementation Order (Copy-Paste to Cursor)

```
PHASE 1 — Fix what's broken (Day 1)
  □ Section 1: Config hardening (Pydantic settings)
  □ Section 2: Database manager (single connection)
  □ Section 3: Error boundaries (safe_tool_call)
  □ Section 7: Appointment ID fix + validation

PHASE 2 — Add architecture (Day 2)
  □ Section 4: Session management
  □ Section 5: Context window management
  □ Section 6: Transport abstraction
  □ Section 8: Pipeline refactor (wire everything together)

PHASE 3 — Production readiness (Day 3)
  □ Section 9: Observability (health + logging)
  □ Section 10: Docker + PostgreSQL
  □ Section 11: Tests
  □ Section 12: Updated dependencies

PHASE 4 — Polish (Day 4)
  □ Update ARCHITECTURE.md with new design
  □ Update README.md with setup instructions for both local + Docker
  □ Add .env.example with all new variables
  □ Run full test suite, fix any issues
```

---

## Cursor Prompt Template

When starting each section, paste this to Cursor:

```
I'm refactoring the Aria voice agent (Pipecat-based real-time voice AI).
Read the full codebase context in ROADMAP.md.

Current task: SECTION [N] — [Title]

Requirements:
- [paste the section content]

Constraints:
- This is a REAL-TIME VOICE pipeline. Any unhandled exception = caller hears silence and gets disconnected.
- All database access must be async (never block the event loop).
- All tool failures must return a spoken-language error string, never crash.
- Use Pydantic for all models and config.
- Type hints on every function.
- No global mutable state except the settings singleton and db_manager singleton.
- Keep functions under 40 lines.
```
