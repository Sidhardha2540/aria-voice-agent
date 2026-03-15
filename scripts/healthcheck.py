"""
Docker HEALTHCHECK script.
Runs check_health(); exits 0 if healthy, 1 otherwise.
"""
import asyncio
import sys

# Ensure project root is on path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from agent.database.manager import db_manager
from agent.observability.health import check_health


async def main() -> int:
    try:
        # Start DB if not already (e.g. first health check before first call)
        if db_manager._conn is None and db_manager._pool is None:
            await db_manager.startup()
        result = await check_health()
        if result.get("status") == "healthy":
            return 0
        return 1
    except Exception:
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
