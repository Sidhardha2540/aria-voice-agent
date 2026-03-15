"""
Application entrypoint and lifecycle.
Delegates to the Pipecat pipeline (agent.bot). DB is started on first use via get_shared_db() in run_bot.
On process exit (Ctrl+C), shuts down the DB so the process can exit completely.
"""
import atexit
import asyncio
from loguru import logger

from pipecat.runner.run import main


def _shutdown_db():
    """Run DB shutdown with a timeout so the process never hangs on exit."""
    try:
        from agent.database.manager import db_manager
        if db_manager._conn is None and db_manager._pool is None:
            return
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(db_manager.shutdown(), timeout=2.0))
            logger.info("Database closed on exit.")
        except asyncio.TimeoutError:
            logger.warning("Database shutdown timed out; exiting anyway.")
        finally:
            loop.close()
    except Exception as e:
        logger.debug("Exit cleanup: {}", e)


# So that Ctrl+C / process exit closes the DB and the process can fully stop
atexit.register(_shutdown_db)


if __name__ == "__main__":
    main()
