"""
Apply Pipecat dev-runner CLI defaults from Settings and detect port conflicts.
Pipecat only reads --host/--port from sys.argv, not from .env directly.
"""
import socket
import sys
from typing import Any

from loguru import logger


def apply_runner_argv_from_settings(argv: list[str], settings: Any) -> None:
    if "--host" not in argv:
        argv.extend(["--host", settings.host])
        logger.info(
            "[CONFIG] Dev server bind host: {} (set HOST in .env; try http://127.0.0.1:{}/client)",
            settings.host,
            settings.port,
        )
    if "--port" not in argv:
        argv.extend(["--port", str(settings.port)])
        if settings.port != 7860:
            logger.info("[CONFIG] Using port {} from .env (PORT=)", settings.port)


def exit_if_tcp_port_already_listening(host: str, port: int) -> None:
    """
    If something already accepts TCP on this port, the new uvicorn cannot bind (WinError 10048).
    Pipecat still prints 'Bot ready!' after bind failure — browser then hits the wrong process.
    """
    check = "127.0.0.1"
    if host and host not in ("0.0.0.0", "::", ""):
        check = "127.0.0.1" if host in ("localhost", "::1") else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((check, port)) == 0:
                logger.error(
                    "[ARIA] Port {} is already in use on {} — another process is listening. "
                    "The WebRTC client will not reach this bot.\n"
                    "  Fix: stop the other process, or set PORT=7861 in .env and restart.\n"
                    "  Windows: netstat -ano | findstr :{}\n"
                    "  Then open: http://127.0.0.1:{}/client",
                    port,
                    check,
                    port,
                    port,
                )
                sys.exit(1)
    except OSError as e:
        logger.debug("Port check skipped: {}", e)
