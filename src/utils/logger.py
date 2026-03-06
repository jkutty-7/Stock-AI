"""Structured logging setup for the application."""

import logging
import sys

from src.config import settings


def setup_logging() -> None:
    """Configure structured logging with console and file handlers."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    try:
        handlers.append(logging.FileHandler("stock_ai.log", encoding="utf-8"))
    except OSError:
        pass  # Read-only filesystem (e.g. Vercel) — skip file logging

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
