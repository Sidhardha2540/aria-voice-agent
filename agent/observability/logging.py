"""
Structured logging configuration.
All log lines can include session_id when available (set via contextvar or logger.bind).
"""
import sys

from loguru import logger

from agent.config import settings


def setup_logging() -> None:
    """Configure loguru for structured logging."""
    logger.remove()

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
