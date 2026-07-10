"""Litefuse (Langfuse SDK) reporter implementation.

Uses the ``langfuse`` Python SDK's context-manager API to create traces
and generations.  The ``langfuse`` import is deferred to ``__init__`` so
the application can start even when the package is missing — the factory
falls back to :class:`NullReporter` in that case.

Trace hierarchy:
  - ``start_trace()`` creates a root span for the Langfuse trace.
  - ``record_generation()`` and ``record_span()`` each create observations
    nested under the trace via ``trace_context={\"trace_id\": trace_id}``.
  - ``end_trace()`` finalizes and exits the trace context manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ainrf.observability.protocol import ObservabilityConfig, ObservabilityReporter

if TYPE_CHECKING:
    from langfuse.types import TraceContext

_LOG = logging.getLogger(__name__)


class LitefuseReporter(ObservabilityReporter):
    """Concrete reporter backed by a Litefuse / Langfuse instance.

    Uses the ``langfuse`` Python SDK's context-manager API to create traces
    and generations.  The ``langfuse`` import is deferred to ``__init__`` so
    the application can start even when the package is missing — the factory
    falls back to :class:`NullReporter` in that case.
    """

    def __init__(self, config: ObservabilityConfig) -> None:
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.base_url,
        )
        self._config = config
        # Map OpenScience trace_id → active root context, span, and attributes context.
        self._active_traces: dict[str, tuple[Any, Any, Any | None]] = {}

    def _trace_context(self, trace_id: str) -> TraceContext:
        active_trace = self._active_traces.get(trace_id)
        if active_trace is not None:
            root_span = active_trace[1]
            return {
                "trace_id": root_span.trace_id,
                "parent_span_id": root_span.id,
            }
        return {"trace_id": self._client.create_trace_id(seed=trace_id)}

    # ------------------------------------------------------------------
    # Health check (used by the factory to verify connectivity)
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Return ``True`` if the Litefuse backend is reachable."""
        try:
            return self._client.auth_check()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # ObservabilityReporter interface
    # ------------------------------------------------------------------

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
        # Langfuse represents a trace as a hierarchy of observations; the first
        # span is the root observation and supplies the SDK-generated trace ID.
        ctx = self._client.start_as_current_observation(
            as_type="span",
            name=name,
            input=input,
            metadata=metadata,
        )
        span = ctx.__enter__()
        attributes_ctx: Any | None = None
        if user_id or session_id:
            try:
                from langfuse import propagate_attributes

                attributes_ctx = propagate_attributes(
                    user_id=user_id,
                    session_id=session_id,
                    trace_name=name,
                )
                attributes_ctx.__enter__()
            except Exception:
                attributes_ctx = None
                pass  # non-critical
        self._active_traces[trace_id] = (ctx, span, attributes_ctx)

    def end_trace(
        self,
        trace_id: str,
        *,
        output: Any = None,
        error: str | None = None,
    ) -> None:
        entry = self._active_traces.pop(trace_id, None)
        if entry is None:
            return
        ctx, span, attributes_ctx = entry
        try:
            if output is not None:
                span.update(output=output)
            if error is not None:
                span.update(metadata={"error": error})
        finally:
            if attributes_ctx is not None:
                attributes_ctx.__exit__(None, None, None)
            ctx.__exit__(None, None, None)

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
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = output
        if usage_details is not None:
            update_kwargs["usage_details"] = usage_details
        if cost_details is not None:
            update_kwargs["cost_details"] = cost_details
        if metadata is not None:
            update_kwargs["metadata"] = metadata

        # Nest the generation under the parent trace via trace_context
        # so it appears in the Litefuse/Langfuse UI as a child observation.
        ctx = self._client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input,
            trace_context=self._trace_context(trace_id),
        )
        gen = ctx.__enter__()
        if update_kwargs:
            gen.update(**update_kwargs)
        ctx.__exit__(None, None, None)

    def record_span(
        self,
        trace_id: str,
        name: str,
        *,
        input: Any = None,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = output
        if metadata is not None:
            update_kwargs["metadata"] = metadata

        # Nest the span under the parent trace via trace_context.
        ctx = self._client.start_as_current_observation(
            as_type="span",
            name=name,
            input=input,
            trace_context=self._trace_context(trace_id),
        )
        span = ctx.__enter__()
        if update_kwargs:
            span.update(**update_kwargs)
        ctx.__exit__(None, None, None)

    def flush(self) -> None:
        self._client.flush()
