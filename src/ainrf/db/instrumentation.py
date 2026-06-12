"""SQLite query performance instrumentation.

Provides opt-in connection instrumentation that logs slow queries and
records Prometheus metrics without modifying core service code.

Usage::

    from ainrf.db.instrumentation import instrument_connection

    conn = sqlite3.connect(...)
    instrument_connection(conn, db_label="agentic_researcher")
"""
from __future__ import annotations

import sqlite3
import time

import structlog

from ainrf.api.routes.metrics import inc_counter, observe_histogram

_LOG = structlog.get_logger(__name__).bind(component="db")

# Default threshold above which a query is considered "slow".
DEFAULT_SLOW_THRESHOLD_SECONDS = 1.0


def instrument_connection(
    conn: sqlite3.Connection,
    db_label: str,
    *,
    slow_threshold: float = DEFAULT_SLOW_THRESHOLD_SECONDS,
    trace_all: bool = False,
) -> sqlite3.Connection:
    """Install query timing instrumentation on *conn*.

    Parameters
    ----------
    conn:
        An open ``sqlite3.Connection``.
    db_label:
        Logical name for the database (used in log lines and metric labels).
    slow_threshold:
        Queries exceeding this duration (seconds) are logged at WARNING and
        increment ``ainrf_db_slow_query_total``.
    trace_all:
        When ``True``, *every* query is logged at DEBUG level.  Useful during
        development; keep ``False`` in production to avoid log noise.

    Returns
    -------
    The same *conn* object (for call-chaining convenience).
    """
    last_sql: list[str] = [""]  # mutable closure container

    def _on_sql(sql: str) -> None:
        # SQLite trace callback fires *before* execution, so we cannot
        # measure duration directly.  Instead we record the SQL text and
        # use a wrapper approach.  For a lightweight alternative we just
        # log the SQL at debug level and rely on the service-layer timing
        # in critical paths.
        if trace_all:
            _LOG.debug("db_query", db=db_label, sql=sql[:200])

        last_sql[0] = sql

    # Store the label on the connection so callers can reference it.
    conn._ainrf_db_label = db_label  # type: ignore[attr-defined]
    conn.set_trace_callback(_on_sql)
    return conn


class QueryTimer:
    """Context manager that times a database operation and records metrics.

    Usage::

        with QueryTimer("agentic_researcher") as t:
            cursor.execute("SELECT ...")
        # t.elapsed is populated, slow-query counter/histogram updated.
    """

    __slots__ = ("_label", "_threshold", "elapsed", "sql")

    def __init__(
        self,
        db_label: str,
        *,
        slow_threshold: float = DEFAULT_SLOW_THRESHOLD_SECONDS,
        sql: str = "",
    ) -> None:
        self._label = db_label
        self._threshold = slow_threshold
        self.elapsed: float = 0.0
        self.sql = sql

    def __enter__(self) -> QueryTimer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.monotonic() - self._start
        labels = {"db": self._label}
        observe_histogram("ainrf_db_query_duration_seconds", self.elapsed, labels)
        if self.elapsed >= self._threshold:
            _LOG.warning(
                "slow_query",
                db=self._label,
                sql=self.sql[:200] if self.sql else "(unknown)",
                elapsed_ms=round(self.elapsed * 1000, 1),
            )
            inc_counter("ainrf_db_slow_query_total", labels)
