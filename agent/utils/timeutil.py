"""Timezone-aware UTC timestamps (replaces deprecated datetime.utcnow())."""
from datetime import datetime, timezone


def utc_now_iso_z() -> str:
    """ISO-8601 UTC with Z suffix (JS/Mongo-friendly)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
