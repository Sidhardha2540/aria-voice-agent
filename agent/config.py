"""
Configuration for Aria voice agent.
Loads all environment variables and provides sensible defaults.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (works even when runner spawns subprocesses with different cwd)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# API Keys (required for STT, LLM, TTS — no Daily/transport keys needed with SmallWebRTC)
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Cartesia voice — warm, professional female voice for "Aria"
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "b7d50908-b17c-442d-ad8d-810c63997ed9")

# Groq model: "llama-3.1-8b-instant" (low latency) vs "llama-3.3-70b-versatile" (smarter)
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Dual-LLM routing: fast (8B) for simple, smart (70B) for complex
ENABLE_DUAL_LLM = os.getenv("ENABLE_DUAL_LLM", "false").lower() in ("1", "true", "yes")
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "llama-3.1-8b-instant")
GROQ_MODEL_SMART = os.getenv("GROQ_MODEL_SMART", "llama-3.3-70b-versatile")
USE_LLM_CLASSIFIER = os.getenv("USE_LLM_CLASSIFIER", "true").lower() in ("1", "true", "yes")

# Latency tuning — defaults optimized for <300ms
DEEPGRAM_UTTERANCE_END_MS = int(os.getenv("DEEPGRAM_UTTERANCE_END_MS", "300"))
DEEPGRAM_ENDPOINTING = int(os.getenv("DEEPGRAM_ENDPOINTING", "100"))
TTS_LOW_LATENCY = os.getenv("TTS_LOW_LATENCY", "true").lower() in ("1", "true", "yes")

# LLM tuning
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "80"))
MAX_CONTEXT_TURNS = int(os.getenv("MAX_CONTEXT_TURNS", "10"))

# Database
DB_PATH = os.getenv("DB_PATH", "data/aria.db")

# Server
PORT = int(os.getenv("PORT", "7860"))
HOST = os.getenv("HOST", "0.0.0.0")

# Optional
LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN", "")

# Backchanneling: subtle acknowledgments ("mhm", "okay") during long user turns (TODO, not implemented)
ENABLE_BACKCHANNELING = os.getenv("ENABLE_BACKCHANNELING", "false").lower() in ("1", "true", "yes")
