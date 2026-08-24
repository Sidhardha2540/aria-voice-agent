"""
Health check for all dependencies: DB, API keys.
Used by Docker HEALTHCHECK, load balancers, and monitoring.
"""
import time

from agent.config import is_configured_secret, settings
from agent.database.manager import db_manager


REQUIRED_API_KEYS = {
    "deepgram": "deepgram_api_key",
    "openai": "openai_api_key",
    "cartesia": "cartesia_api_key",
}


def check_required_secret(service: str, value: str | None) -> dict:
    """Build a health-check entry for a required secret."""

    if is_configured_secret(value):
        return {"status": "ok"}
    return {
        "status": "missing_key",
        "detail": f"{service.upper()} API key is missing or still set to an example value.",
    }


def overall_status(checks: dict) -> str:
    """Classify aggregate health from individual check statuses."""

    statuses = [check["status"] for check in checks.values()]
    if all(status == "ok" for status in statuses):
        return "healthy"
    if "error" in statuses or "missing_key" in statuses:
        return "unhealthy"
    return "degraded"


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
    for service, attr_name in REQUIRED_API_KEYS.items():
        checks[service] = check_required_secret(service, getattr(settings, attr_name))

    checks["configuration"] = {
        "status": "ok",
        "transport_mode": settings.transport_mode,
        "model": settings.openai_model,
        "host": settings.host,
        "port": settings.port,
        "tts_low_latency": settings.tts_low_latency,
    }

    overall = overall_status(checks)

    return {"status": overall, "checks": checks}
