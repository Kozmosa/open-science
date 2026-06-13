"""Litefuse (Langfuse SDK) reporter implementation."""
from __future__ import annotations

import logging
from typing import Any

from ainrf.observability.protocol import ObservabilityConfig, ObservabilityReporter

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
        # Map AINRF trace_id → active Langfuse span context.
        self._active_traces: dict[str, Any] = {}

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
        ctx = self._client.start_as_current_observation(
            as_type="span",
            name=name,
            trace_context={"trace_id": trace_id},
            input=input,
            metadata=metadata,
        )
        span = ctx.__enter__()
        if user_id or session_id:
            try:
                from langfuse import propagate_attributes

                attrs: dict[str, Any] = {}
                if user_id:
                    attrs["user_id"] = user_id
                if session_id:
                    attrs["session_id"] = session_id
                propagate_attributes(**attrs)
            except Exception:
                pass  # non-critical
        self._active_traces[trace_id] = (ctx, span)

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
        ctx, span = entry
        if output is not None:
            span.update(output=output)
        if error is not None:
            span.update(metadata={"error": error})
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

        ctx = self._client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input,
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

        ctx = self._client.start_as_current_observation(
            as_type="span",
            name=name,
            input=input,
        )
        span = ctx.__enter__()
        if update_kwargs:
            span.update(**update_kwargs)
        ctx.__exit__(None, None, None)

    def flush(self) -> None:
        self._client.flush()
