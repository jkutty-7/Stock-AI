"""Structured logging setup for the application.

V2 improvements:
- Bug fix: OSError on file open now warns instead of silently passing
- Log rotation: RotatingFileHandler (10 MB, 5 backups)
- Optional JSON logging via LOG_JSON=true
- Configurable log file path via LOG_FILE
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from src.config import settings


class _JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (no extra dependencies required)."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        data: dict[str, Any] = {
            "ts": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging() -> None:
    """Configure structured logging with console and rotating file handlers."""
    handlers: list[logging.Handler] = []

    # --- Console handler ---
    console = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        console.setFormatter(_JsonFormatter())
    else:
        console.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    handlers.append(console)

    # --- Rotating file handler ---
    try:
        fh = RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        if settings.log_json:
            fh.setFormatter(_JsonFormatter())
        else:
            fh.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        handlers.append(fh)
    except OSError as e:
        # Bug fix #1: warn instead of silently ignoring (read-only filesystem, permissions, etc.)
        print(f"[WARNING] Could not open log file '{settings.log_file}': {e} — file logging disabled", file=sys.stderr)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
