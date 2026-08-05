from __future__ import annotations

import datetime
import logging
import os
import sys
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO, cast

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

_LOG_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _env_flag(name: str, default: bool = False, *, compatibility_name: str | None = None) -> bool:
    value = os.environ.get(name)
    if value is None and compatibility_name is not None:
        value = os.environ.get(compatibility_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def development_logging_enabled() -> bool:
    """Return whether verbose development diagnostics are enabled.

    Production is an explicit safety boundary: a stray development flag can
    never turn on the high-volume diagnostic stream there.
    """

    return _env_flag(
        "AINRF_DEV_LOGGING", compatibility_name="OPENSCIENCE_DEV_LOGGING"
    ) and not _env_flag("AINRF_PRODUCTION", compatibility_name="OPENSCIENCE_PRODUCTION")


def effective_log_level() -> int:
    """Return the process-wide level for both stdlib and structlog output."""

    if _env_flag("AINRF_PRODUCTION", compatibility_name="OPENSCIENCE_PRODUCTION"):
        return logging.INFO
    default = "DEBUG" if development_logging_enabled() else "INFO"
    configured = (
        os.environ.get("AINRF_LOG_LEVEL", os.environ.get("OPENSCIENCE_LOG_LEVEL", default))
        .strip()
        .upper()
    )
    return _LOG_LEVELS.get(configured, _LOG_LEVELS[default])


def _drop_below_effective_level(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Filter PrintLogger events, whose backend has no stdlib level gate."""

    method_level = _LOG_LEVELS.get(method_name.upper(), logging.INFO)
    if method_level < effective_log_level():
        raise structlog.DropEvent
    return event_dict


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
            _drop_below_effective_level,
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
    root.setLevel(effective_log_level())

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
            _drop_below_effective_level,
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
