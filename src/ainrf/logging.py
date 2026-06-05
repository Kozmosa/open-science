from __future__ import annotations

import datetime
import logging
from pathlib import Path

import structlog


def configure_logging(state_root: Path) -> None:
    """Configure structlog + stdlib logging to write to a dated log file.

    Log file: ``<state_root>/logs/backend-YYYYMMDD.log``
    The date is fixed at server start time so a single process always writes
    to one file.  A ``RotatingFileHandler`` could be added later for very
    long-running processes.
    """
    log_dir = state_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d")
    log_path = log_dir / f"backend-{today}.log"

    # --- stdlib side ---
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any existing handlers (e.g. a previous basicConfig) so we don't
    # duplicate output when configure_logging is called more than once in tests.
    root.handlers.clear()

    formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # --- structlog side ---
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Uvicorn uses its own loggers — route them to the file too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True  # let root handler emit to file
