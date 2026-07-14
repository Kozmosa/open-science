from __future__ import annotations

import datetime
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO, cast

import structlog


class _CurrentStderr:
    """A stderr handle that follows the active process stream.

    ``CliRunner`` and pytest temporarily replace then close ``sys.stderr``.
    Structlog caches its logger factory, so passing the stream object directly
    leaves later domain logging pointed at that closed capture.  The proxy is
    intentionally tiny: every write resolves the current standard-error
    stream while still keeping CLI diagnostics off JSON stdout.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()


_CURRENT_STDERR: TextIO = cast(TextIO, _CurrentStderr())


def configure_cli_logging() -> None:
    """Send structured CLI diagnostics to stderr without touching state.

    Management commands commonly return a single JSON document on stdout.
    Keeping diagnostics on stderr makes that transport contract machine
    readable while still retaining correlation-rich telemetry for operators.
    Long-lived server processes immediately replace this lightweight setup
    with :func:`configure_logging`, which also writes their dated log file.
    """

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=_CURRENT_STDERR),
        wrapper_class=structlog.BoundLogger,
        # CLI and server startup can reconfigure structlog in one process.
        # Cached module-level loggers would retain stale processors after that.
        cache_logger_on_first_use=False,
    )


def configure_logging(state_root: Path) -> None:
    """Configure structlog + stdlib logging to write to a dated log file.

    Log file: ``<state_root>/logs/backend-YYYYMMDD.log``
    The date is fixed at server start time so a single process always writes
    to one file.  Logs are also emitted to **stdout** so that ``docker logs``
    captures structured output.

    File rotation: each file grows up to 50 MB with up to 10 backups.
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

    file_handler = RotatingFileHandler(
        log_path, maxBytes=50_000_000, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

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
        cache_logger_on_first_use=False,
    )

    # Uvicorn uses its own loggers — route them to the file too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True  # let root handler emit to file
