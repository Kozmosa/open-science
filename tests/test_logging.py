"""Tests for ainrf.logging module."""

from __future__ import annotations

import io
import logging
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import structlog

from ainrf.logging import configure_cli_logging, configure_logging

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_root_handlers() -> Generator[None]:
    """Remove FileHandlers added by configure_logging so pytest teardown
    never tries to close a tmp_path-backed FD that no longer exists."""

    root = logging.getLogger()
    saved = list(root.handlers)
    yield
    root.handlers.clear()
    root.handlers.extend(saved)


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


def test_cli_logging_does_not_retain_a_closed_capture_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CLI invocation must not poison later in-process structured logs."""

    original_config = structlog.get_config()
    first_stderr = io.StringIO()
    second_stderr = io.StringIO()
    try:
        monkeypatch.setattr(sys, "stderr", first_stderr)
        configure_cli_logging()
        first_stderr.close()
        monkeypatch.setattr(sys, "stderr", second_stderr)

        structlog.get_logger("cli-capture-regression").info("still-writable")

        assert "still-writable" in second_stderr.getvalue()
    finally:
        structlog.configure(**original_config)
