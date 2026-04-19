"""
Configuration for Aria voice agent.
Pydantic Settings — validated at startup, not at first use during a live call.
"""
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# Load .env from project root (Pydantic also loads it; this ensures cwd-independent load)
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    import dotenv
    dotenv.load_dotenv(_env_file)


class Settings(BaseSettings):
    # Required — app MUST NOT start without these (set in .env)
    deepgram_api_key: str
    openai_api_key: str
    cartesia_api_key: str

    # Optional with validated defaults
    cartesia_voice_id: str = "b7d50908-b17c-442d-ad8d-810c63997ed9"
    openai_model: str = "gpt-4o-mini"

    # Dual-LLM routing (optional): fast model for simple turns, smart for complex
    enable_dual_llm: bool = False
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_smart: str = "gpt-4o"
    use_llm_classifier: bool = True

    # Latency tuning — validated ranges (DIAGNOSIS: 500/200 for faster turn-taking)
    deepgram_utterance_end_ms: int = Field(default=500, ge=100, le=3000)
    deepgram_endpointing: int = Field(default=200, ge=50, le=1000)
    tts_low_latency: bool = True

    # LLM tuning (max_completion_tokens=200 for tool-calling turns; temp 0.4 for speed)
    llm_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=200, ge=10, le=500)

    # Database
    database_url: str = "sqlite+aiosqlite:///data/aria.db"

    # Redis (for session state in multi-instance deployments)
    redis_url: str | None = None

    # Transport
    transport_mode: str = "webrtc"

    # Server — bind address for Pipecat dev runner (uvicorn). Use 127.0.0.1 for reliable WebRTC on
    # Windows (localhost can resolve to ::1 while stack listens on IPv4). Use 0.0.0.0 in Docker/LAN.
    port: int = Field(default=7860, ge=1, le=65535)
    host: str = "127.0.0.1"

    # Observability
    log_level: str = "INFO"
    logfire_token: str | None = None

    # Context management (lower = less latency from smaller prompts; trim earlier)
    max_context_messages: int = Field(default=40, ge=10, le=200)
    context_summary_threshold: int = Field(default=30, ge=8, le=180)

    # Backchanneling (TODO)
    enable_backchanneling: bool = False

    # Learn from every call: record outcomes and inject recent learnings into system prompt
    enable_learn_from_feedback: bool = True
    feedback_max_entries: int = Field(default=50, ge=5, le=200)
    feedback_max_chars: int = Field(default=600, ge=200, le=2000)

    model_config = {
        "env_file": str(_env_file) if _env_file.exists() else None,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("transport_mode")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        allowed = {"webrtc", "twilio", "daily"}
        v_lower = v.lower() if v else "webrtc"
        if v_lower not in allowed:
            raise ValueError(f"transport_mode must be one of {allowed}")
        return v_lower

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("sqlite", "postgresql")):
            raise ValueError("database_url must start with sqlite or postgresql")
        return v

    @field_validator("deepgram_api_key", "openai_api_key", "cartesia_api_key")
    @classmethod
    def required_api_keys_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("API key must not be empty. Set in .env or environment.")
        return v.strip()


# Singleton — created at import; crashes fast if required keys missing or invalid
settings = Settings()

# Backward-compat names used by existing code (bot.py, etc.)
def __getattr__(name: str):
    if name == "DEEPGRAM_API_KEY":
        return settings.deepgram_api_key
    if name == "OPENAI_API_KEY":
        return settings.openai_api_key
    if name == "CARTESIA_API_KEY":
        return settings.cartesia_api_key
    if name == "CARTESIA_VOICE_ID":
        return settings.cartesia_voice_id
    if name == "OPENAI_MODEL":
        return settings.openai_model
    if name == "ENABLE_DUAL_LLM":
        return settings.enable_dual_llm
    if name == "OPENAI_MODEL_FAST":
        return settings.openai_model_fast
    if name == "OPENAI_MODEL_SMART":
        return settings.openai_model_smart
    if name == "USE_LLM_CLASSIFIER":
        return settings.use_llm_classifier
    if name == "DEEPGRAM_UTTERANCE_END_MS":
        return settings.deepgram_utterance_end_ms
    if name == "DEEPGRAM_ENDPOINTING":
        return settings.deepgram_endpointing
    if name == "TTS_LOW_LATENCY":
        return settings.tts_low_latency
    if name == "LLM_TEMPERATURE":
        return settings.llm_temperature
    if name == "LLM_MAX_TOKENS":
        return settings.llm_max_tokens
    if name == "MAX_CONTEXT_TURNS":
        return settings.context_summary_threshold
    if name == "DB_PATH":
        u = settings.database_url
        if u.startswith("sqlite+aiosqlite:///"):
            return u.replace("sqlite+aiosqlite:///", "")
        return "data/aria.db"
    if name == "PORT":
        return settings.port
    if name == "HOST":
        return settings.host
    if name == "LOGFIRE_TOKEN":
        return settings.logfire_token or ""
    if name == "ENABLE_BACKCHANNELING":
        return settings.enable_backchanneling
    if name == "ENABLE_LEARN_FROM_FEEDBACK":
        return settings.enable_learn_from_feedback
    if name == "FEEDBACK_MAX_ENTRIES":
        return settings.feedback_max_entries
    if name == "FEEDBACK_MAX_CHARS":
        return settings.feedback_max_chars
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
