"""SQLite query performance instrumentation.

Provides opt-in connection instrumentation that logs slow queries and
records Prometheus metrics without modifying core service code.

Usage::

    from ainrf.db.instrumentation import instrument_connection, QueryTimer

    conn = sqlite3.connect(...)
    instrument_connection(conn, db_label="agentic_researcher")

    with QueryTimer("agentic_researcher", conn=conn) as t:
        cursor.execute("SELECT ...")
    # t.elapsed is populated; slow-query counter/histogram updated.
    # t.sql is automatically populated from the connection's trace callback.
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
        # SQLite trace callback fires *before* execution, so we stash the
        # SQL text on the connection object where QueryTimer can read it
        # after the query completes.
        if trace_all:
            _LOG.debug("db_query", db=db_label, sql=sql[:200])
        last_sql[0] = sql

    # Store label and SQL buffer on the connection so QueryTimer can read them.
    conn._ainrf_db_label = db_label  # type: ignore[attr-defined]
    conn._ainrf_last_sql = last_sql  # type: ignore[attr-defined]
    conn.set_trace_callback(_on_sql)
    return conn


class QueryTimer:
    """Context manager that times a database operation and records metrics.

    When a *conn* is provided, ``sql`` is automatically populated from the
    connection's trace callback (set by :func:`instrument_connection`).
    An explicit ``sql`` parameter always takes precedence.

    Usage::

        with QueryTimer("agentic_researcher", conn=conn) as t:
            cursor.execute("SELECT ...")
        # t.elapsed is populated; t.sql contains the actual query text.
    """

    __slots__ = ("_label", "_threshold", "elapsed", "_explicit_sql", "_conn")

    def __init__(
        self,
        db_label: str,
        *,
        slow_threshold: float = DEFAULT_SLOW_THRESHOLD_SECONDS,
        sql: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._label = db_label
        self._threshold = slow_threshold
        self.elapsed: float = 0.0
        self._explicit_sql = sql
        self._conn = conn

    @property
    def sql(self) -> str:
        """The SQL text of the query being timed.

        Returns the explicit ``sql`` parameter if set; otherwise reads from
        the connection's trace callback (``conn._ainrf_last_sql``).  Falls
        back to ``"(unknown)"`` if neither is available.
        """
        if self._explicit_sql:
            return self._explicit_sql
        if self._conn is not None and hasattr(self._conn, "_ainrf_last_sql"):
            last_sql: list[str] = self._conn._ainrf_last_sql  # type: ignore[union-attr]
            return last_sql[0] if last_sql[0] else "(unknown)"
        return "(unknown)"

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
                sql=self.sql[:200],
                elapsed_ms=round(self.elapsed * 1000, 1),
            )
            inc_counter("ainrf_db_slow_query_total", labels)
