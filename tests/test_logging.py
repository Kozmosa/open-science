"""Tests for ainrf.logging module."""

from __future__ import annotations

import logging
from pathlib import Path

from ainrf.logging import configure_logging


def test_configure_logging_creates_dated_log_file(tmp_path: Path) -> None:
    """configure_logging creates <state_root>/logs/backend-YYYYMMDD.log."""
    configure_logging(tmp_path)

    log_dir = tmp_path / "logs"
    assert log_dir.is_dir()

    log_files = list(log_dir.glob("backend-*.log"))
    assert len(log_files) == 1
    # Filename format: backend-YYYYMMDD.log (8 digits)
    name = log_files[0].name
    assert name.startswith("backend-")
    assert name.endswith(".log")
    date_part = name[len("backend-") : -len(".log")]
    assert len(date_part) == 8 and date_part.isdigit()


def test_configure_logging_writes_to_file(tmp_path: Path) -> None:
    """Messages logged via stdlib appear in the log file."""
    configure_logging(tmp_path)

    logger = logging.getLogger("test.module")
    logger.info("hello from test")

    # Flush handlers
    for handler in logging.getLogger().handlers:
        handler.flush()

    log_files = list((tmp_path / "logs").glob("backend-*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "hello from test" in content


def test_configure_logging_idempotent(tmp_path: Path) -> None:
    """Calling configure_logging twice does not duplicate handlers."""
    configure_logging(tmp_path)
    first_count = len(logging.getLogger().handlers)

    configure_logging(tmp_path)
    assert len(logging.getLogger().handlers) == first_count
