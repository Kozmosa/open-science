"""LLM observability abstraction layer.

Provides a decoupled interface for tracing LLM calls, recording token usage,
and reporting to external observability backends (e.g. Litefuse).

When no backend is configured, all operations are no-ops via NullReporter.
"""

from __future__ import annotations

from ainrf.observability.protocol import (
    NullReporter,
    ObservabilityConfig,
    ObservabilityReporter,
    SafeReporter,
)
from ainrf.observability.factory import get_reporter, reset_reporter

__all__ = [
    "get_reporter",
    "reset_reporter",
    "NullReporter",
    "ObservabilityConfig",
    "ObservabilityReporter",
    "SafeReporter",
]
