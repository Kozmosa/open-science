"""Observability reporter protocol, configuration, and null/safe implementations."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class ObservabilityConfig:
    """Configuration for the LLM observability backend."""

    enabled: bool = False
    base_url: str = ""
    secret_key: str = ""
    public_key: str = ""

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        """Read configuration from ``AINRF_OBSERVABILITY_*`` environment variables."""
        return cls(
            enabled=os.environ.get("AINRF_OBSERVABILITY_ENABLED", "").lower()
            in ("1", "true", "yes"),
            base_url=os.environ.get("AINRF_OBSERVABILITY_BASE_URL", ""),
            secret_key=os.environ.get("AINRF_OBSERVABILITY_SECRET_KEY", ""),
            public_key=os.environ.get("AINRF_OBSERVABILITY_PUBLIC_KEY", ""),
        )


class ObservabilityReporter(ABC):
    """Abstraction for LLM observability reporting.

    Implementations report traces, generations (LLM calls), and spans to an
    external backend.  All methods must be safe to call from any thread or
    async context and must **never** raise — errors should be logged and
    swallowed to prevent observability failures from disrupting the main
    application flow.
    """

    @abstractmethod
    def start_trace(
        self,
        trace_id: str,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        input: Any = None,
    ) -> None:
        """Begin a new trace (maps 1:1 to a task or batch operation)."""
        ...

    @abstractmethod
    def end_trace(
        self,
        trace_id: str,
        *,
        output: Any = None,
        error: str | None = None,
    ) -> None:
        """Finalize a trace previously started with :meth:`start_trace`."""
        ...

    @abstractmethod
    def record_generation(
        self,
        trace_id: str,
        name: str,
        *,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
        input: Any = None,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a single LLM generation within a trace."""
        ...

    @abstractmethod
    def record_span(
        self,
        trace_id: str,
        name: str,
        *,
        input: Any = None,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a generic span (non-LLM operation) within a trace."""
        ...

    @abstractmethod
    def flush(self) -> None:
        """Flush any buffered observations to the backend."""
        ...


class NullReporter(ObservabilityReporter):
    """No-op implementation used when observability is disabled."""

    def start_trace(self, trace_id: str, name: str, **kwargs: Any) -> None:
        pass

    def end_trace(self, trace_id: str, **kwargs: Any) -> None:
        pass

    def record_generation(self, trace_id: str, name: str, **kwargs: Any) -> None:
        pass

    def record_span(self, trace_id: str, name: str, **kwargs: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class SafeReporter(ObservabilityReporter):
    """Wraps any reporter, catching and logging all errors.

    Prevents observability backend failures from propagating into the main
    application logic.
    """

    def __init__(self, inner: ObservabilityReporter) -> None:
        self._inner = inner

    def start_trace(self, trace_id: str, name: str, **kwargs: Any) -> None:
        try:
            self._inner.start_trace(trace_id, name, **kwargs)
        except Exception:
            _LOG.warning("observability.start_trace.failed", exc_info=True)

    def end_trace(self, trace_id: str, **kwargs: Any) -> None:
        try:
            self._inner.end_trace(trace_id, **kwargs)
        except Exception:
            _LOG.warning("observability.end_trace.failed", exc_info=True)

    def record_generation(self, trace_id: str, name: str, **kwargs: Any) -> None:
        try:
            self._inner.record_generation(trace_id, name, **kwargs)
        except Exception:
            _LOG.warning("observability.record_generation.failed", exc_info=True)

    def record_span(self, trace_id: str, name: str, **kwargs: Any) -> None:
        try:
            self._inner.record_span(trace_id, name, **kwargs)
        except Exception:
            _LOG.warning("observability.record_span.failed", exc_info=True)

    def flush(self) -> None:
        try:
            self._inner.flush()
        except Exception:
            _LOG.warning("observability.flush.failed", exc_info=True)
