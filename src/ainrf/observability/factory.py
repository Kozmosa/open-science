"""Singleton factory for the observability reporter."""
from __future__ import annotations

import logging

from ainrf.observability.protocol import (
    NullReporter,
    ObservabilityConfig,
    ObservabilityReporter,
    SafeReporter,
)

_LOG = logging.getLogger(__name__)

_reporter: ObservabilityReporter | None = None


def get_reporter(config: ObservabilityConfig | None = None) -> ObservabilityReporter:
    """Return the global :class:`ObservabilityReporter` singleton.

    On first call the reporter is initialised from *config* (or environment
    variables if *config* is ``None``).  Subsequent calls return the cached
    instance regardless of *config* — call :func:`reset_reporter` to clear it.
    """
    global _reporter
    if _reporter is not None:
        return _reporter

    if config is None:
        config = ObservabilityConfig.from_env()

    if not config.enabled:
        _LOG.debug("observability.disabled")
        _reporter = SafeReporter(NullReporter())
        return _reporter

    try:
        from ainrf.observability.litefuse_reporter import LitefuseReporter

        inner = LitefuseReporter(config)
        # Verify connectivity.
        if not inner.is_healthy():
            raise ConnectionError("Litefuse health check failed")
        _reporter = SafeReporter(inner)
        _LOG.info("observability.connected", base_url=config.base_url)
    except ImportError:
        _LOG.warning(
            "observability.langfuse_not_installed",
            extra={"hint": "pip install langfuse to enable Litefuse observability"},
        )
        _reporter = SafeReporter(NullReporter())
    except Exception:
        _LOG.warning("observability.init_failed", exc_info=True)
        _reporter = SafeReporter(NullReporter())

    return _reporter


def reset_reporter() -> None:
    """Clear the cached reporter singleton.

    Primarily used in tests to force re-initialisation.
    """
    global _reporter
    _reporter = None
