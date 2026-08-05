"""Tests for ainrf.logging module."""

from __future__ import annotations

import io
import logging
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import structlog

from ainrf.logging import configure_cli_logging, configure_logging, effective_log_level

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


def test_development_logging_enables_debug_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AINRF_DEV_LOGGING", "1")
    monkeypatch.delenv("AINRF_PRODUCTION", raising=False)
    monkeypatch.delenv("AINRF_LOG_LEVEL", raising=False)

    configure_logging(tmp_path)
    assert effective_log_level() == logging.DEBUG
    logging.getLogger("test.development").debug("development details")

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = next((tmp_path / "logs").glob("backend-*.log")).read_text(encoding="utf-8")
    assert "development details" in content


def test_production_overrides_development_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AINRF_DEV_LOGGING", "1")
    monkeypatch.setenv("AINRF_PRODUCTION", "1")
    monkeypatch.setenv("AINRF_LOG_LEVEL", "DEBUG")

    configure_logging(tmp_path)
    assert effective_log_level() == logging.INFO
    logger = logging.getLogger("test.production")
    logger.debug("must stay hidden")
    logger.info("production info")

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = next((tmp_path / "logs").glob("backend-*.log")).read_text(encoding="utf-8")
    assert "must stay hidden" not in content
    assert "production info" in content


def test_cli_logging_suppresses_debug_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = structlog.get_config()
    stderr = io.StringIO()
    try:
        monkeypatch.setattr(sys, "stderr", stderr)
        monkeypatch.setenv("AINRF_PRODUCTION", "1")
        monkeypatch.setenv("AINRF_DEV_LOGGING", "1")
        configure_cli_logging()

        logger = structlog.get_logger("cli-production")
        logger.debug("hidden cli details")
        logger.info("visible cli status")

        content = stderr.getvalue()
        assert "hidden cli details" not in content
        assert "visible cli status" in content
    finally:
        structlog.configure(**original_config)


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
