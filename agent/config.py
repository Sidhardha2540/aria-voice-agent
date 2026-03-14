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

# Groq model: "llama-3.3-70b-versatile" (smarter) vs "llama-3.1-8b-instant" (~100ms faster TTFB)
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Latency tuning — set in .env to reduce response time (see .env.example)
DEEPGRAM_UTTERANCE_END_MS = int(os.getenv("DEEPGRAM_UTTERANCE_END_MS", "1000"))  # lower = faster turn, may cut off slow speakers
DEEPGRAM_ENDPOINTING = int(os.getenv("DEEPGRAM_ENDPOINTING", "250"))
TTS_LOW_LATENCY = os.getenv("TTS_LOW_LATENCY", "false").lower() in ("1", "true", "yes")  # TOKEN mode = ~100ms less, slightly choppier

# Database
DB_PATH = os.getenv("DB_PATH", "data/aria.db")

# Server
PORT = int(os.getenv("PORT", "7860"))
HOST = os.getenv("HOST", "0.0.0.0")

# Optional
LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN", "")
