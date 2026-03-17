"""
Health check for all dependencies: DB, API keys.
Used by Docker HEALTHCHECK, load balancers, and monitoring.
"""
import time

from agent.config import settings
from agent.database.manager import db_manager


async def check_health() -> dict:
    """
    Check all dependencies. Returns a dict with:
    {
        "status": "healthy" | "degraded" | "unhealthy",
        "checks": {
            "database": {"status": "ok", "latency_ms": 2.1} | {"status": "error", "error": "..."},
            "deepgram": {"status": "ok"},
            "openai": {"status": "ok"},
            "cartesia": {"status": "ok"},
        }
    }
    """
    checks = {}

    # Database check (only if already started)
    try:
        if db_manager._conn is None and db_manager._pool is None:
            checks["database"] = {"status": "not_initialized"}
        else:
            start = time.monotonic()
            await db_manager.execute_one("SELECT 1")
            latency = (time.monotonic() - start) * 1000
            checks["database"] = {"status": "ok", "latency_ms": round(latency, 1)}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}

    # API key presence (no external calls)
    checks["deepgram"] = {"status": "ok" if (settings.deepgram_api_key and settings.deepgram_api_key.strip()) else "missing_key"}
    checks["openai"] = {"status": "ok" if (settings.openai_api_key and settings.openai_api_key.strip()) else "missing_key"}
    checks["cartesia"] = {"status": "ok" if (settings.cartesia_api_key and settings.cartesia_api_key.strip()) else "missing_key"}

    statuses = [c["status"] for c in checks.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif "error" in statuses or "missing_key" in statuses:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}
