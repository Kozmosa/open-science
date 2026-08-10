"""Bounded, redacted telemetry for the authoritative domain control plane.

The domain worker has no HTTP listener of its own, while Prometheus scrapes
the API process.  Control-plane facts therefore need to be collected from the
durable SQLite stores rather than from process-local counters alone.  This
module keeps the two concerns together:

* :func:`refresh_domain_metrics` exports current durable health at scrape time;
* event helpers increment bounded counters and emit redacted structured logs
  for security-relevant or release-gating transitions.

No metric label contains user-, tenant-, filesystem-, or idempotency-key
values.  Correlation identifiers live only in structured logs, and private
paths and secret-shaped fields are replaced with stable fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias, cast
import structlog

_LOG = structlog.get_logger("domain_telemetry")

_SUBMISSION_BACKLOG_STATES = (
    "queued",
    "stale_claimed",
    "stale_delivering",
    "delivery_unknown",
)
_SUBMISSION_STALE_AFTER_SECONDS = 30.0
_IDEMPOTENCY_OUTCOMES = ("accepted", "missing", "invalid", "conflict", "reused", "stored", "other")
_PERMISSION_RESOURCES = (
    "project",
    "workspace",
    "task",
    "environment",
    "literature",
    "overview",
    "other",
)
_PERMISSION_REASONS = (
    "not_visible",
    "editor_required",
    "owner_required",
    "publish_required",
    "admin_required",
    "environment_grant_required",
    "authenticated_user_required",
    "actor_unavailable",
    "tenant_owner_required",
    "registry_manager_required",
    "other",
)
_SQLITE_OPERATIONS = (
    "connection_open",
    "connection_execute",
    "connection_executescript",
    "domain_metrics_auth_read",
    "domain_metrics_literature_read",
    "domain_metrics_overview_read",
    "domain_metrics_refresh",
    "other",
)
_SQLITE_ERROR_TYPES = (
    "OperationalError",
    "IntegrityError",
    "DatabaseError",
    "Error",
    "other",
)
_SQLITE_ERROR_KINDS = ("busy_or_locked", "readonly", "corrupt", "other")
_SAGA_STATUSES = (
    "pending",
    "creating_task",
    "task_created",
    "completed",
    "retryable_failed",
)
_OVERVIEW_JOB_STATUSES = (
    "queued",
    "retry_wait",
    "running",
    "succeeded",
    "partial",
    "failed",
)
_OVERVIEW_CARD_STATUSES = ("ok", "partial", "stale", "unavailable", "failed", "unknown")
_OVERVIEW_UNTRUSTED_SNAPSHOT_AGE_SECONDS = 30 * 60 * 60 + 1
_SAGA_EVENT_OUTCOMES = (
    "intent_created",
    "task_created",
    "completed",
    "retryable_failure",
    "other",
)
_OVERVIEW_EVENT_OUTCOMES = (
    "queued",
    "reused",
    "succeeded",
    "partial",
    "retry_wait",
    "failed",
    "other",
)
_OVERVIEW_EVENT_TRIGGERS = ("manual", "scheduled", "catchup", "other")
_SENSITIVE_FIELD_PARTS = (
    "secret",
    "password",
    "credential",
    "authorization",
    "auth",
    "api_key",
    "access_key",
    "private_key",
    "token",
    "cookie",
    "bearer",
)
_PATH_FIELD_PARTS = ("path", "directory", "cwd", "root")
_SAFE_STRING_FIELD_NAMES = frozenset(
    {
        "component",
        "environment_id",
        "error_type",
        "error_kind",
        "event",
        "intent_id",
        "job_id",
        "mode",
        "operation",
        "outcome",
        "phase",
        "project_id",
        "reason",
        "replacement",
        "resource",
        "route",
        "runtime_execution_id",
        "scope",
        "source",
        "status",
        "submission_id",
        "task_id",
        "trigger",
        "turn_id",
        "user_id",
        "workspace_id",
    }
)
_TELEMETRY_STORE_FILENAME = "domain_telemetry.sqlite3"
_TELEMETRY_ANCHOR_FILENAME = "domain_telemetry_anchor.json"
_TELEMETRY_DELIVERY_FAILURE_LATCH_FILENAME = "domain_telemetry_delivery_failure.json"
_TELEMETRY_STORE_SCHEMA_VERSION = 3
_DURABLE_COUNTER_LABEL_VALUES: dict[str, dict[str, tuple[str, ...]]] = {
    "ainrf_domain_idempotency_requests_total": {"outcome": _IDEMPOTENCY_OUTCOMES},
    "ainrf_domain_literature_saga_events_total": {"outcome": _SAGA_EVENT_OUTCOMES},
    "ainrf_domain_overview_refresh_events_total": {
        "outcome": _OVERVIEW_EVENT_OUTCOMES,
        "trigger": _OVERVIEW_EVENT_TRIGGERS,
    },
    "ainrf_domain_permission_denied_total": {
        "resource": _PERMISSION_RESOURCES,
        "reason": _PERMISSION_REASONS,
    },
    "ainrf_domain_sqlite_errors_total": {
        "operation": _SQLITE_OPERATIONS,
        "error_type": _SQLITE_ERROR_TYPES,
        "kind": _SQLITE_ERROR_KINDS,
    },
}
_DURABLE_COUNTER_LABELS: dict[str, tuple[str, ...]] = {
    name: tuple(values) for name, values in _DURABLE_COUNTER_LABEL_VALUES.items()
}

_CURRENT_MIN_SOURCE_SCHEMA_VERSION: dict[str, int] = {
    "agentic_researcher": 33,
    "auth": 7,
    "literature": 9,
}
_CURRENT_CONTROL_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "_schema_version": ("database", "version"),
    "tasks": ("task_id", "status", "updated_at"),
    "conversation_task_authorities": ("task_id", "authority"),
    "task_turns": ("turn_id", "task_id", "status", "updated_at"),
    "turn_submissions": (
        "submission_id",
        "task_id",
        "status",
        "created_at",
        "claimed_at",
        "delivering_at",
        "updated_at",
    ),
    "next_turn_submissions": ("submission_id", "task_id", "status"),
    "runtime_executions": ("runtime_execution_id", "task_id", "turn_id", "status", "updated_at"),
    "domain_idempotency_requests": ("actor_user_id", "scope", "idempotency_key"),
}
_CURRENT_AUTH_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "_schema_version": ("database", "version"),
    "users": ("id", "status"),
    "environment_access": (
        "environment_id",
        "user_id",
        "grant_version",
        "status",
        "updated_at",
        "revoked_at",
    ),
}
_CURRENT_LITERATURE_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "_schema_version": ("database", "version"),
    "literature_research_task_intents": (
        "intent_id",
        "user_id",
        "paper_id",
        "idempotency_key",
        "task_id",
        "status",
        "created_at",
        "updated_at",
    ),
}
_CURRENT_OVERVIEW_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "overview_snapshots": (
        "snapshot_id",
        "owner_user_id",
        "created_at",
        "source_status",
        "attention_required",
    ),
    "overview_refresh_jobs": ("job_id", "owner_user_id", "status"),
    "overview_refresh_card_states": ("owner_user_id", "card_id", "status"),
}
_TELEMETRY_SOURCES = ("control", "auth", "literature", "overview")
_TELEMETRY_SOURCE_STATES = ("ready", "missing", "schema_invalid", "unavailable")

DurableCounterKey: TypeAlias = tuple[str, tuple[tuple[str, str], ...]]

# The state root is bound by the connection factory and by request middleware.
# Context-local state prevents an ASGI request for one test/runtime from ever
# writing its durable telemetry into another root.  The module intentionally
# does not inspect process environment variables here: a CLI option and API
# config are the authoritative state-root inputs.
_TELEMETRY_STATE_ROOT: ContextVar[Path | None] = ContextVar(
    "domain_telemetry_state_root", default=None
)
_LAST_GOOD_SCRAPES: dict[Path, _CollectedDomainMetrics] = {}
_LAST_SUCCESS_TIMESTAMPS: dict[Path, float] = {}


@dataclass(frozen=True, slots=True)
class DomainTelemetrySnapshot:
    """The durable values emitted during one Prometheus scrape."""

    submission_oldest_pending_age_seconds: float
    submission_backlog_count: int
    idempotency_record_count: int
    literature_pending_age_seconds: float
    overview_oldest_age_seconds: float
    overview_missing_active_user_count: int
    overview_attention_required_count: int


@dataclass(frozen=True, slots=True)
class _CollectedDomainMetrics:
    """One complete, internally consistent durable scrape result."""

    snapshot: DomainTelemetrySnapshot
    submission_backlog: Mapping[str, int]
    saga_counts: Mapping[str, int]
    overview_job_counts: Mapping[str, int]
    overview_card_states: Mapping[str, int]
    durable_counters: Mapping[DurableCounterKey, float]


class _TelemetryStoreError(RuntimeError):
    """A local durable telemetry store was unavailable or malformed."""


class _TelemetrySourceReadinessError(_TelemetryStoreError):
    """A current-product scrape lacks a required authoritative source."""

    def __init__(self, source: str, state: str) -> None:
        super().__init__(f"domain telemetry source {source} is {state}")
        self.source = source
        self.state = state


def bind_domain_telemetry_state_root(state_root: Path) -> Token[Path | None]:
    """Bind one authoritative runtime root for the current execution context."""

    return _TELEMETRY_STATE_ROOT.set(Path(state_root).resolve())


def restore_domain_telemetry_state_root(token: Token[Path | None]) -> None:
    """Restore a previous telemetry root after a request scope exits."""

    _TELEMETRY_STATE_ROOT.reset(token)


def configure_domain_telemetry_state_root(state_root: Path) -> None:
    """Set the current process/context root after opening a runtime database."""

    _TELEMETRY_STATE_ROOT.set(Path(state_root).resolve())


def domain_telemetry_state_root_for_database(db_path: str | Path) -> Path | None:
    """Return a state root only for a database directly inside ``runtime/``."""

    try:
        path = Path(db_path).resolve()
    except (OSError, ValueError):
        return None
    return path.parent.parent if path.parent.name == "runtime" else None


def _counter(
    name: str,
    labels: Mapping[str, str] | None = None,
    *,
    durable: bool = False,
    state_root: Path | None = None,
) -> bool:
    """Increment a metric without allowing telemetry failures to break work."""

    try:
        from ainrf.telemetry.metrics import inc_counter

        inc_counter(name, dict(labels) if labels else None)
    except Exception:  # pragma: no cover - metrics must stay non-fatal
        _LOG.debug("domain_telemetry_counter_unavailable", metric=name)
    if not durable:
        return True
    delivered = _persist_durable_counter(name, labels or {}, state_root=state_root)
    if not delivered:
        _latch_telemetry_delivery_failure(
            _resolved_state_root(state_root),
            metric_name=name,
            error=RuntimeError("durable counter delivery failed"),
        )
    return delivered


def _gauge(name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
    """Publish one gauge without allowing telemetry failures to break work."""

    try:
        from ainrf.telemetry.metrics import set_gauge

        set_gauge(name, value, dict(labels) if labels else None)
    except Exception:  # pragma: no cover - metrics must stay non-fatal
        _LOG.debug("domain_telemetry_gauge_unavailable", metric=name)


def _set_counter(name: str, value: float, labels: Mapping[str, str]) -> None:
    """Hydrate one API-process counter from a durable monotonic total."""

    try:
        from ainrf.telemetry.metrics import set_counter

        set_counter(name, value, dict(labels))
    except Exception:  # pragma: no cover - metrics must stay non-fatal
        _LOG.debug("domain_telemetry_counter_hydration_unavailable", metric=name)


def _resolved_state_root(state_root: Path | None = None) -> Path | None:
    if state_root is not None:
        return Path(state_root).resolve()
    return _TELEMETRY_STATE_ROOT.get()


def _telemetry_store_path(state_root: Path) -> Path:
    return state_root / "runtime" / _TELEMETRY_STORE_FILENAME


def _telemetry_anchor_path(state_root: Path) -> Path:
    """Return the sidecar lifecycle marker kept apart from the SQLite file."""

    return state_root / "runtime" / _TELEMETRY_ANCHOR_FILENAME


def _telemetry_delivery_failure_latch_path(state_root: Path) -> Path:
    """Return the fail-closed marker for a lost durable event."""

    return state_root / "runtime" / _TELEMETRY_DELIVERY_FAILURE_LATCH_FILENAME


def _write_json_once(path: Path, payload: Mapping[str, object]) -> bool:
    """Atomically write an immutable, non-secret runtime safety marker.

    The marker does not record event payload, user data, paths, or keys.  It
    is deliberately created once: a subsequent successful scrape cannot
    erase evidence that a release-gating transition might have been lost.
    """

    encoded = (json.dumps(dict(payload), ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return True
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _ensure_telemetry_anchor(state_root: Path) -> None:
    """Create the sidecar lifecycle anchor or reject a missing known sidecar."""

    anchor = _telemetry_anchor_path(state_root)
    if anchor.exists():
        return
    if not _write_json_once(
        anchor,
        {
            "schema_version": _TELEMETRY_STORE_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
        },
    ):
        raise _TelemetryStoreError("cannot persist telemetry anchor")


def _latch_telemetry_delivery_failure(
    state_root: Path | None,
    *,
    metric_name: str,
    error: BaseException,
) -> None:
    """Persist a release-blocking indicator when an event cannot be stored."""

    if state_root is None:
        return
    root = Path(state_root).resolve()
    try:
        root.joinpath("runtime").mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    _write_json_once(
        _telemetry_delivery_failure_latch_path(root),
        {
            "schema_version": _TELEMETRY_STORE_SCHEMA_VERSION,
            "first_observed_at": datetime.now(UTC).isoformat(),
            "metric": metric_name if metric_name in _DURABLE_COUNTER_LABELS else "other",
            "error_type": type(error).__name__,
        },
    )


def _telemetry_delivery_failure_latched(state_root: Path) -> bool:
    """Return true if delivery uncertainty is recorded or cannot be inspected."""

    latch = _telemetry_delivery_failure_latch_path(state_root)
    try:
        return latch.exists()
    except OSError:
        # Inability to inspect the latch is itself not healthy telemetry.
        return True


def _open_telemetry_store(state_root: Path, *, create: bool) -> sqlite3.Connection | None:
    """Open the sidecar independently of the instrumented connection factory.

    The connection factory itself emits SQLite telemetry.  Using it here would
    recurse when the telemetry store is locked or damaged, so this deliberately
    uses a small raw SQLite connection with the same bounded wait semantics.
    """

    runtime_root = state_root / "runtime"
    path = _telemetry_store_path(state_root)
    anchor = _telemetry_anchor_path(state_root)
    if not path.is_file() and not create:
        if anchor.exists():
            raise _TelemetryStoreError("telemetry sidecar disappeared after initialization")
        return None
    needs_bootstrap = not path.exists()
    if needs_bootstrap and anchor.exists():
        raise _TelemetryStoreError("telemetry sidecar disappeared after initialization")
    if create:
        runtime_root.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        if create:
            conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
        else:
            # All telemetry hydrations are observational.  In particular, a
            # maintenance-mode API must never open the sidecar in a mode that
            # could initialize a journal or mutate SQLite connection state.
            conn = _read_only(path)
        if create:
            if needs_bootstrap:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS domain_telemetry_counter_totals (
                    metric_name TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    value REAL NOT NULL CHECK (value >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(metric_name, labels_json)
                );
                CREATE TABLE IF NOT EXISTS domain_telemetry_snapshots (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            _ensure_telemetry_anchor(state_root)
        return conn
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        raise _TelemetryStoreError(type(exc).__name__) from exc
    except OSError as exc:
        if conn is not None:
            conn.close()
        raise _TelemetryStoreError(type(exc).__name__) from exc


def _canonical_counter_labels(name: str, labels: Mapping[str, str]) -> DurableCounterKey:
    allowed_values = _DURABLE_COUNTER_LABEL_VALUES.get(name)
    if allowed_values is None:
        raise ValueError(f"unsupported durable telemetry metric: {name}")
    if set(labels) != set(allowed_values):
        raise ValueError(f"invalid labels for durable telemetry metric: {name}")
    normalized_items: list[tuple[str, str]] = []
    for label, allowed in allowed_values.items():
        value = labels[label]
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"invalid label value for durable telemetry metric: {name}")
        normalized_items.append((label, value))
    normalized = tuple(normalized_items)
    return name, normalized


def _counter_labels_json(labels: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(dict(labels), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _persist_durable_counter(
    name: str,
    labels: Mapping[str, str],
    *,
    state_root: Path | None,
) -> bool:
    """Increment a shared, bounded counter without exposing event payloads.

    The rows contain only metric names and pre-bounded labels.  Correlation
    fields remain in the redacted log stream and never enter this store.
    """

    root = _resolved_state_root(state_root)
    if root is None:
        return False
    try:
        metric_name, normalized_labels = _canonical_counter_labels(name, labels)
        labels_json = _counter_labels_json(normalized_labels)
        conn = _open_telemetry_store(root, create=True)
        if conn is None:  # pragma: no cover - create=True always opens or raises
            return False
        try:
            now = datetime.now(UTC).isoformat()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO domain_telemetry_counter_totals
                    (metric_name, labels_json, value, updated_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(metric_name, labels_json) DO UPDATE SET
                    value = domain_telemetry_counter_totals.value + 1,
                    updated_at = excluded.updated_at
                """,
                (metric_name, labels_json, now),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except (OSError, ValueError, _TelemetryStoreError, sqlite3.Error) as exc:
        # Callers create a separate fail-closed latch.  The latch is kept
        # outside the damaged sidecar so an API restart cannot turn an event
        # delivery failure into a fabricated clean counter.
        _LOG.warning(
            "domain_telemetry_durable_counter_write_failed",
            metric=name if name in _DURABLE_COUNTER_LABELS else "other",
            error_type=type(exc).__name__,
        )
        return False


def _load_durable_counters(state_root: Path) -> dict[DurableCounterKey, float]:
    conn = _open_telemetry_store(state_root, create=False)
    if conn is None:
        return {}
    try:
        tables = _tables(conn)
        if "domain_telemetry_counter_totals" not in tables:
            raise _TelemetryStoreError("missing counter table")
        values: dict[DurableCounterKey, float] = {}
        rows = conn.execute(
            "SELECT metric_name, labels_json, value FROM domain_telemetry_counter_totals"
        ).fetchall()
        for row in rows:
            name = str(row["metric_name"])
            try:
                decoded = json.loads(str(row["labels_json"]))
            except json.JSONDecodeError as exc:
                raise _TelemetryStoreError("invalid durable counter labels") from exc
            if not isinstance(decoded, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in decoded.items()
            ):
                raise _TelemetryStoreError("invalid durable counter labels")
            key = _canonical_counter_labels(name, decoded)
            value = float(row["value"])
            if not math.isfinite(value) or value < 0:
                raise _TelemetryStoreError("invalid durable counter value")
            values[key] = value
        return values
    except (sqlite3.Error, ValueError, _TelemetryStoreError) as exc:
        raise _TelemetryStoreError(type(exc).__name__) from exc
    finally:
        conn.close()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _normalized_field_name(name: str) -> str:
    """Normalize camelCase and punctuation before applying redaction policy."""

    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return camel_split.replace("-", "_").lower()


def _bounded_label(value: str, allowed: tuple[str, ...]) -> str:
    return value if value in allowed else "other"


def _redacted_fields(fields: Mapping[str, object]) -> dict[str, object]:
    """Return structured-log fields under a fail-closed value policy.

    Only explicitly named correlation and control fields retain strings.  Any
    arbitrary string is fingerprinted, so a future exception/detail field
    cannot silently become a tenant-data or credential log channel.
    """

    safe: dict[str, object] = {}
    for name, value in fields.items():
        normalized = _normalized_field_name(name)
        if "idempotency" in normalized and "fingerprint" not in normalized:
            safe[f"{name}_fingerprint"] = _fingerprint(value)
        elif any(part in normalized for part in _PATH_FIELD_PARTS):
            safe[f"{name}_fingerprint"] = _fingerprint(value)
        elif (
            any(part in normalized for part in _SENSITIVE_FIELD_PARTS)
            or normalized == "key"
            or normalized.endswith("_key")
        ):
            safe[name] = "[REDACTED]"
        elif value is None or isinstance(value, (bool, int, float)):
            safe[name] = value
        elif isinstance(value, str) and (
            normalized in _SAFE_STRING_FIELD_NAMES or normalized.endswith("_fingerprint")
        ):
            safe[name] = value[:256]
        else:
            safe[f"{name}_fingerprint"] = _fingerprint(value)
    return safe


def log_domain_event(event: str, /, **fields: object) -> None:
    """Write one redacted, correlation-friendly structured domain event."""

    _LOG.info(event, **_redacted_fields(fields))


def record_idempotency_event(
    outcome: str,
    *,
    scope: str | None = None,
    idempotency_key: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    task_id: str | None = None,
    turn_id: str | None = None,
    submission_id: str | None = None,
    runtime_execution_id: str | None = None,
    state_root: Path | None = None,
) -> None:
    """Record transport or durable idempotency acceptance and reuse safely."""

    normalized_outcome = _bounded_label(outcome, _IDEMPOTENCY_OUTCOMES)
    _counter(
        "ainrf_domain_idempotency_requests_total",
        {"outcome": normalized_outcome},
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_idempotency",
        outcome=normalized_outcome,
        scope=scope,
        idempotency_key=idempotency_key,
        user_id=user_id,
        project_id=project_id,
        workspace_id=workspace_id,
        task_id=task_id,
        turn_id=turn_id,
        submission_id=submission_id,
        runtime_execution_id=runtime_execution_id,
    )


def _correlation_id(
    request: Mapping[str, object],
    response: Mapping[str, object] | None,
    *names: str,
) -> str | None:
    for source in (request, response):
        if source is None:
            continue
        for name in names:
            value = source.get(name)
            if isinstance(value, str) and value:
                return value
    return None


def record_durable_idempotency_event(
    outcome: str,
    *,
    actor_user_id: str,
    scope: str,
    idempotency_key: str,
    request: Mapping[str, object],
    response: Mapping[str, object] | None = None,
    state_root: Path | None = None,
) -> None:
    """Observe a repository-backed idempotency replay or conflict.

    The request/response are used only to recover stable correlation IDs for
    the redacted log; no request values become Prometheus labels or raw logs.
    """

    record_idempotency_event(
        outcome,
        scope=scope,
        idempotency_key=idempotency_key,
        user_id=actor_user_id,
        project_id=_correlation_id(request, response, "project_id"),
        workspace_id=_correlation_id(request, response, "workspace_id"),
        task_id=_correlation_id(request, response, "task_id"),
        turn_id=_correlation_id(request, response, "turn_id", "reserved_turn_id"),
        submission_id=_correlation_id(request, response, "submission_id"),
        runtime_execution_id=_correlation_id(request, response, "runtime_execution_id"),
        state_root=state_root,
    )


def record_permission_denied(
    *,
    resource: str,
    reason: str,
    user_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    task_id: str | None = None,
    environment_id: str | None = None,
    state_root: Path | None = None,
) -> None:
    """Record an authorization denial without adding identifiers to metric labels."""

    normalized_resource = _bounded_label(resource, _PERMISSION_RESOURCES)
    normalized_reason = _bounded_label(reason, _PERMISSION_REASONS)
    _counter(
        "ainrf_domain_permission_denied_total",
        {
            "resource": normalized_resource,
            "reason": normalized_reason,
        },
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_permission_denied",
        resource=normalized_resource,
        reason=normalized_reason,
        user_id=user_id,
        project_id=project_id,
        workspace_id=workspace_id,
        task_id=task_id,
        environment_id=environment_id,
    )


def record_literature_saga_event(
    outcome: str,
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    task_id: str | None = None,
    intent_id: str | None = None,
    idempotency_key: str | None = None,
    state_root: Path | None = None,
) -> None:
    """Emit a redacted durable Literature-to-Task saga event log.

    The saga can run in the no-port domain worker, so a process-local
    Prometheus counter would be invisible to API-process scrapes.  Its bounded
    event total is therefore persisted beside the runtime state, then hydrated
    by :func:`refresh_domain_metrics`; the durable saga-state gauges remain
    the current-state scrape surface.
    """
    normalized_outcome = _bounded_label(outcome, _SAGA_EVENT_OUTCOMES)
    _counter(
        "ainrf_domain_literature_saga_events_total",
        {"outcome": normalized_outcome},
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_literature_saga",
        outcome=normalized_outcome,
        user_id=user_id,
        project_id=project_id,
        workspace_id=workspace_id,
        task_id=task_id,
        intent_id=intent_id,
        idempotency_key=idempotency_key,
    )


def record_overview_event(
    outcome: str,
    *,
    trigger: str,
    user_id: str | None = None,
    job_id: str | None = None,
    state_root: Path | None = None,
) -> None:
    """Emit a redacted durable Overview refresh event log.

    Overview workers have no scrape endpoint.  A bounded durable event total
    is hydrated by the API scrape alongside the durable job/snapshot gauges,
    rather than relying on an API-process-local counter.
    """
    normalized_outcome = _bounded_label(outcome, _OVERVIEW_EVENT_OUTCOMES)
    normalized_trigger = _bounded_label(trigger, _OVERVIEW_EVENT_TRIGGERS)
    _counter(
        "ainrf_domain_overview_refresh_events_total",
        {"outcome": normalized_outcome, "trigger": normalized_trigger},
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_overview_refresh",
        outcome=normalized_outcome,
        trigger=normalized_trigger,
        user_id=user_id,
        job_id=job_id,
    )


def _sqlite_error_kind(error: BaseException) -> str:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return "busy_or_locked"
    if "readonly" in message:
        return "readonly"
    if "corrupt" in message or "malformed" in message:
        return "corrupt"
    return "other"


def _sqlite_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name in _SQLITE_ERROR_TYPES else "other"


def record_sqlite_error(
    *,
    operation: str,
    error: BaseException,
    user_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    task_id: str | None = None,
    state_root: Path | None = None,
) -> None:
    """Record a SQLite failure using only bounded error-class labels."""

    normalized_operation = _bounded_label(operation, _SQLITE_OPERATIONS)
    error_type = _sqlite_error_type(error)
    error_kind = _sqlite_error_kind(error)
    _counter(
        "ainrf_domain_sqlite_errors_total",
        {
            "operation": normalized_operation,
            "error_type": error_type,
            "kind": error_kind,
        },
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_sqlite_error",
        operation=normalized_operation,
        error_type=error_type,
        error_kind=error_kind,
        user_id=user_id,
        project_id=project_id,
        workspace_id=workspace_id,
        task_id=task_id,
    )


def _snapshot_payload(collected: _CollectedDomainMetrics) -> str:
    snapshot = collected.snapshot
    payload = {
        "schema_version": _TELEMETRY_STORE_SCHEMA_VERSION,
        "snapshot": {
            "submission_oldest_pending_age_seconds": (
                snapshot.submission_oldest_pending_age_seconds
            ),
            "submission_backlog_count": snapshot.submission_backlog_count,
            "idempotency_record_count": snapshot.idempotency_record_count,
            "literature_pending_age_seconds": snapshot.literature_pending_age_seconds,
            "overview_oldest_age_seconds": snapshot.overview_oldest_age_seconds,
            "overview_missing_active_user_count": snapshot.overview_missing_active_user_count,
            "overview_attention_required_count": snapshot.overview_attention_required_count,
        },
        "submission_backlog": [
            {"status": status, "value": value}
            for status, value in sorted(collected.submission_backlog.items())
        ],
        "saga_counts": [
            {"status": status, "value": value}
            for status, value in sorted(collected.saga_counts.items())
        ],
        "overview_job_counts": [
            {"status": status, "value": value}
            for status, value in sorted(collected.overview_job_counts.items())
        ],
        "overview_card_states": [
            {"status": status, "value": value}
            for status, value in sorted(collected.overview_card_states.items())
        ],
        "durable_counters": [
            {
                "metric_name": name,
                "labels": dict(labels),
                "value": value,
            }
            for (name, labels), value in sorted(collected.durable_counters.items())
        ],
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _non_negative_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _TelemetryStoreError(f"invalid snapshot {name}")
    return value


def _non_negative_float(value: object, *, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _TelemetryStoreError(f"invalid snapshot {name}")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise _TelemetryStoreError(f"invalid snapshot {name}")
    return converted


def _bounded_count_records(
    payload: Mapping[str, object],
    *,
    key: str,
    label_name: str,
    allowed: tuple[str, ...],
) -> dict[str, int]:
    values = {value: 0 for value in allowed}
    records = payload.get(key)
    if not isinstance(records, list):
        raise _TelemetryStoreError(f"invalid snapshot {key}")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not all(
            isinstance(item_key, str) for item_key in record
        ):
            raise _TelemetryStoreError(f"invalid snapshot {key}")
        typed_record = cast(dict[str, object], record)
        label = typed_record.get(label_name)
        if not isinstance(label, str) or label not in values:
            raise _TelemetryStoreError(f"invalid snapshot {key}")
        if label in seen:
            raise _TelemetryStoreError(f"duplicate snapshot {key}")
        seen.add(label)
        values[label] = _non_negative_int(typed_record.get("value"), name=key)
    if seen != set(allowed):
        raise _TelemetryStoreError(f"incomplete snapshot {key}")
    return values


def _snapshot_from_payload(raw: str) -> _CollectedDomainMetrics:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _TelemetryStoreError("invalid snapshot JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _TELEMETRY_STORE_SCHEMA_VERSION
    ):
        raise _TelemetryStoreError("unsupported telemetry snapshot")
    typed_payload = cast(dict[str, object], payload)
    snapshot_raw = typed_payload.get("snapshot")
    if not isinstance(snapshot_raw, dict) or not all(
        isinstance(item_key, str) for item_key in snapshot_raw
    ):
        raise _TelemetryStoreError("invalid snapshot values")
    typed_snapshot = cast(dict[str, object], snapshot_raw)
    snapshot = DomainTelemetrySnapshot(
        submission_oldest_pending_age_seconds=_non_negative_float(
            typed_snapshot.get("submission_oldest_pending_age_seconds"),
            name="submission_oldest_pending_age_seconds",
        ),
        submission_backlog_count=_non_negative_int(
            typed_snapshot.get("submission_backlog_count"), name="submission_backlog_count"
        ),
        idempotency_record_count=_non_negative_int(
            typed_snapshot.get("idempotency_record_count"), name="idempotency_record_count"
        ),
        literature_pending_age_seconds=_non_negative_float(
            typed_snapshot.get("literature_pending_age_seconds"),
            name="literature_pending_age_seconds",
        ),
        overview_oldest_age_seconds=_non_negative_float(
            typed_snapshot.get("overview_oldest_age_seconds"), name="overview_oldest_age_seconds"
        ),
        overview_missing_active_user_count=_non_negative_int(
            typed_snapshot.get("overview_missing_active_user_count"),
            name="overview_missing_active_user_count",
        ),
        overview_attention_required_count=_non_negative_int(
            typed_snapshot.get("overview_attention_required_count"),
            name="overview_attention_required_count",
        ),
    )
    counter_records = typed_payload.get("durable_counters")
    if not isinstance(counter_records, list):
        raise _TelemetryStoreError("invalid snapshot durable_counters")
    durable_counters: dict[DurableCounterKey, float] = {}
    for record in counter_records:
        if not isinstance(record, dict) or not all(
            isinstance(item_key, str) for item_key in record
        ):
            raise _TelemetryStoreError("invalid snapshot durable_counters")
        typed_record = cast(dict[str, object], record)
        name = typed_record.get("metric_name")
        labels = typed_record.get("labels")
        if (
            not isinstance(name, str)
            or not isinstance(labels, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in labels.items()
            )
        ):
            raise _TelemetryStoreError("invalid snapshot durable_counters")
        typed_labels = cast(dict[str, str], labels)
        counter_key = _canonical_counter_labels(name, typed_labels)
        if counter_key in durable_counters:
            raise _TelemetryStoreError("duplicate snapshot durable_counters")
        durable_counters[counter_key] = _non_negative_float(
            typed_record.get("value"), name="durable_counters"
        )
    return _CollectedDomainMetrics(
        snapshot=snapshot,
        submission_backlog=_bounded_count_records(
            typed_payload,
            key="submission_backlog",
            label_name="status",
            allowed=_SUBMISSION_BACKLOG_STATES,
        ),
        saga_counts=_bounded_count_records(
            typed_payload,
            key="saga_counts",
            label_name="status",
            allowed=_SAGA_STATUSES,
        ),
        overview_job_counts=_bounded_count_records(
            typed_payload,
            key="overview_job_counts",
            label_name="status",
            allowed=_OVERVIEW_JOB_STATUSES,
        ),
        overview_card_states=_bounded_count_records(
            typed_payload,
            key="overview_card_states",
            label_name="status",
            allowed=_OVERVIEW_CARD_STATUSES,
        ),
        durable_counters=durable_counters,
    )


def _persist_collected_snapshot(
    state_root: Path,
    collected: _CollectedDomainMetrics,
    *,
    collected_at: float,
) -> None:
    conn = _open_telemetry_store(state_root, create=True)
    if conn is None:  # pragma: no cover - create=True always opens or raises
        raise _TelemetryStoreError("telemetry store unavailable")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO domain_telemetry_snapshots
                (singleton, schema_version, collected_at, payload_json)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                schema_version = excluded.schema_version,
                collected_at = excluded.collected_at,
                payload_json = excluded.payload_json
            """,
            (
                _TELEMETRY_STORE_SCHEMA_VERSION,
                datetime.fromtimestamp(collected_at, UTC).isoformat(),
                _snapshot_payload(collected),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise _TelemetryStoreError(type(exc).__name__) from exc
    finally:
        conn.close()


def _load_persisted_snapshot(
    state_root: Path,
) -> tuple[_CollectedDomainMetrics, float] | None:
    conn = _open_telemetry_store(state_root, create=False)
    if conn is None:
        return None
    try:
        if "domain_telemetry_snapshots" not in _tables(conn):
            raise _TelemetryStoreError("missing snapshot table")
        row = conn.execute(
            "SELECT schema_version, collected_at, payload_json FROM domain_telemetry_snapshots "
            "WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return None
        if int(row["schema_version"]) != _TELEMETRY_STORE_SCHEMA_VERSION:
            raise _TelemetryStoreError("unsupported snapshot schema")
        collected_at = _parse_timestamp(row["collected_at"])
        if collected_at is None:
            raise _TelemetryStoreError("invalid snapshot timestamp")
        return _snapshot_from_payload(str(row["payload_json"])), collected_at.timestamp()
    except (sqlite3.Error, ValueError, _TelemetryStoreError) as exc:
        raise _TelemetryStoreError(type(exc).__name__) from exc
    finally:
        conn.close()


def refresh_domain_metrics(
    state_root: Path,
    *,
    read_only: bool = False,
) -> DomainTelemetrySnapshot:
    """Publish durable domain health without turning a failed scrape green.

    All authoritative data comes from the shared SQLite stores because the
    dispatcher and planners have no HTTP listener.  If *any* durable read
    fails, the last internally consistent scrape remains exported and a
    separate freshness gauge becomes false.  This avoids a transient lock or
    damaged store resetting a critical backlog/issue gauge to zero.  When
    *read_only* is true (or the persisted maintenance flag is active), the
    scrape uses immutable source reads only; it never opens the telemetry
    sidecar, initializes a sidecar, writes a snapshot, or records a durable
    error.
    """

    root = Path(state_root).resolve()
    configure_domain_telemetry_state_root(root)
    now = datetime.now(UTC)
    control_path = root / "runtime" / "agentic_researcher.sqlite3"
    empty = _empty_collected_metrics()
    source_states = {source: "unavailable" for source in _TELEMETRY_SOURCES}
    effective_read_only = read_only

    try:
        if not control_path.is_file():
            source_states["control"] = "missing"
            raise _TelemetrySourceReadinessError("control", "missing")
        try:
            with closing(
                _maintenance_read_only(control_path, source="control")
                if effective_read_only
                else _read_only(control_path)
            ) as conn:
                tables = _tables(conn)
                effective_read_only = effective_read_only or _maintenance_requires_read_only(
                    conn, tables
                )
                source_states["control"] = _schema_state(
                    conn,
                    tables,
                    _CURRENT_CONTROL_SOURCE_REQUIREMENTS,
                    database_name="agentic_researcher",
                    minimum_version=_CURRENT_MIN_SOURCE_SCHEMA_VERSION["agentic_researcher"],
                )
                source_states["overview"] = _schema_state(
                    conn,
                    tables,
                    _CURRENT_OVERVIEW_SOURCE_REQUIREMENTS,
                    database_name="agentic_researcher",
                    minimum_version=_CURRENT_MIN_SOURCE_SCHEMA_VERSION["agentic_researcher"],
                )
                source_states["auth"] = _external_source_state(
                    root / "runtime" / "auth.sqlite3",
                    _CURRENT_AUTH_SOURCE_REQUIREMENTS,
                    source="auth",
                    database_name="auth",
                    minimum_version=_CURRENT_MIN_SOURCE_SCHEMA_VERSION["auth"],
                    maintenance_read_only=effective_read_only,
                )
                source_states["literature"] = _external_source_state(
                    root / "runtime" / "literature.sqlite3",
                    _CURRENT_LITERATURE_SOURCE_REQUIREMENTS,
                    source="literature",
                    database_name="literature",
                    minimum_version=_CURRENT_MIN_SOURCE_SCHEMA_VERSION["literature"],
                    maintenance_read_only=effective_read_only,
                )
                not_ready = _first_not_ready_source(source_states)
                if not_ready is not None:
                    raise _TelemetrySourceReadinessError(*not_ready)
                submission_age, submission_backlog = _submission_metrics(conn, now)
                idempotency_records = _idempotency_record_count(conn, tables)
                (
                    overview_age,
                    overview_missing,
                    overview_attention,
                    overview_card_states,
                ) = _overview_freshness(
                    conn,
                    tables,
                    root / "runtime" / "auth.sqlite3",
                    now,
                    maintenance_read_only=effective_read_only,
                )
                overview_job_counts = _overview_job_counts(conn, tables)
        except (OSError, sqlite3.Error):
            # Preserve last-known-good risk gauges across a transient read
            # failure, while source readiness and scrape-success remain red.
            # The bounded source-state gauge contains no path or SQLite detail.
            source_states["control"] = "unavailable"
            raise
        literature_age, saga_counts = _literature_saga_metrics(
            root / "runtime" / "literature.sqlite3",
            now,
            maintenance_read_only=effective_read_only,
        )
        durable_counters = {} if effective_read_only else _load_durable_counters(root)
        snapshot = DomainTelemetrySnapshot(
            submission_oldest_pending_age_seconds=submission_age,
            submission_backlog_count=sum(submission_backlog.values()),
            idempotency_record_count=idempotency_records,
            literature_pending_age_seconds=literature_age,
            overview_oldest_age_seconds=overview_age,
            overview_missing_active_user_count=overview_missing,
            overview_attention_required_count=overview_attention,
        )
        collected = _CollectedDomainMetrics(
            snapshot=snapshot,
            submission_backlog=submission_backlog,
            saga_counts=saga_counts,
            overview_job_counts=overview_job_counts,
            overview_card_states=overview_card_states,
            durable_counters=durable_counters,
        )
        if not effective_read_only:
            _persist_collected_snapshot(root, collected, collected_at=now.timestamp())
    except Exception as exc:
        if not effective_read_only:
            record_sqlite_error(operation="domain_metrics_refresh", error=exc, state_root=root)
        if isinstance(exc, _TelemetrySourceReadinessError) and exc.state != "unavailable":
            _publish_collected_metrics(
                empty,
                scrape_success=False,
                last_success_timestamp=math.nan,
                risk_state_known=False,
                telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
                source_states=source_states,
            )
            return empty.snapshot
        collected = _LAST_GOOD_SCRAPES.get(root)
        last_success_timestamp = _LAST_SUCCESS_TIMESTAMPS.get(root)
        if collected is None:
            try:
                persisted = _load_persisted_snapshot(root)
                if persisted is not None:
                    collected, last_success_timestamp = persisted
            except Exception:
                collected = None
                last_success_timestamp = None
        if collected is not None:
            try:
                collected = replace(
                    collected,
                    durable_counters=_load_durable_counters(root),
                )
            except Exception:
                collected = None
                last_success_timestamp = None
        if effective_read_only or collected is None:
            _publish_collected_metrics(
                empty,
                scrape_success=False,
                last_success_timestamp=math.nan,
                risk_state_known=False,
                telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
                source_states=source_states,
            )
            return empty.snapshot
        _publish_collected_metrics(
            collected,
            scrape_success=False,
            last_success_timestamp=last_success_timestamp or math.nan,
            risk_state_known=True,
            telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
            source_states=source_states,
        )
        return collected.snapshot
    if not effective_read_only:
        _LAST_GOOD_SCRAPES[root] = collected
        _LAST_SUCCESS_TIMESTAMPS[root] = now.timestamp()
    _publish_collected_metrics(
        collected,
        scrape_success=True,
        last_success_timestamp=now.timestamp(),
        risk_state_known=True,
        telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
        source_states=source_states,
    )
    return collected.snapshot


def _empty_collected_metrics() -> _CollectedDomainMetrics:
    snapshot = DomainTelemetrySnapshot(
        submission_oldest_pending_age_seconds=0.0,
        submission_backlog_count=0,
        idempotency_record_count=0,
        literature_pending_age_seconds=0.0,
        overview_oldest_age_seconds=0.0,
        overview_missing_active_user_count=0,
        overview_attention_required_count=0,
    )
    return _CollectedDomainMetrics(
        snapshot=snapshot,
        submission_backlog={status: 0 for status in _SUBMISSION_BACKLOG_STATES},
        saga_counts={status: 0 for status in _SAGA_STATUSES},
        overview_job_counts={status: 0 for status in _OVERVIEW_JOB_STATUSES},
        overview_card_states={status: 0 for status in _OVERVIEW_CARD_STATUSES},
        durable_counters={},
    )


def _read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_has_wal_sidecars(path: Path) -> bool:
    return any(path.with_name(f"{path.name}{suffix}").exists() for suffix in ("-wal", "-shm"))


def _maintenance_read_only(path: Path, *, source: str) -> sqlite3.Connection:
    """Open one authoritative source without changing its SQLite sidecars.

    SQLite may create or update a shared-memory sidecar even for a regular
    ``mode=ro`` connection.  Immutable mode prevents that write, but it would
    ignore an existing WAL; a main database with WAL/SHM members is therefore
    not a trustworthy immutable view.  During maintenance we defer that
    source rather than touching it or fabricating a partial read.
    """

    if _sqlite_has_wal_sidecars(path):
        raise _TelemetrySourceReadinessError(source, "unavailable")
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _maintenance_requires_read_only(conn: sqlite3.Connection, tables: set[str]) -> bool:
    """Read the maintenance flag without constructing a writable service.

    A maintenance-mode API has intentionally not initialized
    :class:`DomainMaintenanceService`: its ``status()`` path opens the control
    database through the writable connection factory.  Telemetry already has
    a read-only control connection, so it can conservatively decide whether a
    scrape must avoid creating or updating its sidecar from that connection.
    """

    if "domain_maintenance_state" not in tables:
        return False
    if not {"singleton", "is_active"} <= _columns(conn, "domain_maintenance_state"):
        return True
    row = conn.execute(
        "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return True
    value = row["is_active"]
    return not (isinstance(value, int) and not isinstance(value, bool) and value == 0)


def _schema_state(
    conn: sqlite3.Connection,
    tables: set[str],
    requirements: Mapping[str, tuple[str, ...]],
    *,
    database_name: str,
    minimum_version: int,
) -> str:
    """Return a bounded readiness state without exposing a database path."""

    for table, required_columns in requirements.items():
        if table not in tables or not set(required_columns) <= _columns(conn, table):
            return "schema_invalid"
    row = conn.execute(
        "SELECT version FROM _schema_version WHERE database = ?", (database_name,)
    ).fetchone()
    if (
        row is None
        or not isinstance(row["version"], int)
        or isinstance(row["version"], bool)
        or int(row["version"]) < minimum_version
    ):
        return "schema_invalid"
    return "ready"


def _external_source_state(
    path: Path,
    requirements: Mapping[str, tuple[str, ...]],
    *,
    source: str,
    database_name: str,
    minimum_version: int,
    maintenance_read_only: bool,
) -> str:
    """Probe an external SQLite source without treating absence as an empty source."""

    if not path.is_file():
        return "missing"
    try:
        opener = (
            _maintenance_read_only(path, source=source)
            if maintenance_read_only
            else _read_only(path)
        )
        with closing(opener) as conn:
            return _schema_state(
                conn,
                _tables(conn),
                requirements,
                database_name=database_name,
                minimum_version=minimum_version,
            )
    except (_TelemetrySourceReadinessError, OSError, sqlite3.Error):
        return "unavailable"


def _first_not_ready_source(source_states: Mapping[str, str]) -> tuple[str, str] | None:
    for source in _TELEMETRY_SOURCES:
        state = source_states.get(source, "unavailable")
        if state != "ready":
            return source, state
    return None


def _submission_metrics(
    conn: sqlite3.Connection,
    now: datetime,
) -> tuple[float, dict[str, int]]:
    """Mirror the private worker Interface's recoverable submission states.

    A queued next Turn remains intentionally blocked while its predecessor is
    active, so it is excluded until ``next_turn_submissions`` marks it ready.
    Claimed and delivering rows become risk backlog only after the same
    bounded recovery interval used by ``ConversationExecutionService``.
    ``delivery_unknown`` is always operator-visible because replay is fenced.
    """

    counts = {state: 0 for state in _SUBMISSION_BACKLOG_STATES}
    rows = conn.execute(
        """
        SELECT submission.status, submission.created_at, submission.claimed_at,
               submission.delivering_at, submission.updated_at,
               next_turn.status AS next_turn_status
        FROM turn_submissions AS submission
        LEFT JOIN next_turn_submissions AS next_turn
          ON next_turn.submission_id = submission.submission_id
        WHERE submission.status IN ('queued', 'claimed', 'delivering', 'delivery_unknown')
        """
    ).fetchall()
    ages: list[float] = []
    for row in rows:
        status = str(row["status"])
        state: str | None = None
        anchor: object | None = row["created_at"]
        if status == "queued" and row["next_turn_status"] in (None, "ready"):
            state = "queued"
        elif status == "claimed" and _submission_timestamp_is_stale(row["claimed_at"], now):
            state = "stale_claimed"
            anchor = row["claimed_at"] or row["updated_at"]
        elif status == "delivering" and _submission_timestamp_is_stale(row["delivering_at"], now):
            state = "stale_delivering"
            anchor = row["delivering_at"] or row["updated_at"]
        elif status == "delivery_unknown":
            state = "delivery_unknown"
            anchor = row["updated_at"]
        if state is not None:
            counts[state] += 1
            ages.append(_risk_age_seconds(anchor, now))
    return max(ages, default=0.0), counts


def _submission_timestamp_is_stale(value: object | None, now: datetime) -> bool:
    timestamp = _parse_timestamp(value)
    if timestamp is None or timestamp > now:
        return True
    return (now - timestamp).total_seconds() >= _SUBMISSION_STALE_AFTER_SECONDS


def _risk_age_seconds(value: object | None, now: datetime) -> float:
    timestamp = _parse_timestamp(value)
    if timestamp is None or timestamp > now:
        return float(_OVERVIEW_UNTRUSTED_SNAPSHOT_AGE_SECONDS)
    return (now - timestamp).total_seconds()


def _idempotency_record_count(conn: sqlite3.Connection, tables: set[str]) -> int:
    if "domain_idempotency_requests" not in tables:
        return 0
    row = conn.execute("SELECT COUNT(*) AS count FROM domain_idempotency_requests").fetchone()
    return int(row["count"]) if row is not None else 0


def _overview_freshness(
    conn: sqlite3.Connection,
    tables: set[str],
    auth_path: Path,
    now: datetime,
    *,
    maintenance_read_only: bool = False,
) -> tuple[float, int, int, dict[str, int]]:
    card_states = {status: 0 for status in _OVERVIEW_CARD_STATUSES}
    if "overview_snapshots" not in tables:
        active_users = set(_active_user_ids(auth_path, maintenance_read_only=maintenance_read_only))
        return 0.0, len(active_users), len(active_users), card_states
    columns = _columns(conn, "overview_snapshots")
    source_status = "source_status" if "source_status" in columns else "'unknown' AS source_status"
    attention_required = (
        "attention_required" if "attention_required" in columns else "1 AS attention_required"
    )
    rows = conn.execute(
        f"""
        SELECT snapshot_id, owner_user_id, created_at,
               {source_status}, {attention_required}
        FROM overview_snapshots
        ORDER BY owner_user_id, created_at DESC, snapshot_id DESC
        """
    ).fetchall()
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        owner_user_id = row["owner_user_id"]
        if isinstance(owner_user_id, str) and owner_user_id not in latest:
            latest[owner_user_id] = row
    active_users = set(_active_user_ids(auth_path, maintenance_read_only=maintenance_read_only))
    missing = len(active_users.difference(latest))
    tracked_users = active_users or set(latest)
    candidate_ages: list[float] = []
    attention_users = set(active_users.difference(latest))
    for owner_user_id, row in latest.items():
        if owner_user_id not in tracked_users:
            continue
        age = _trusted_overview_age_seconds(row["created_at"], now)
        if age is None:
            # A malformed or future snapshot timestamp cannot prove current
            # Overview data.  Keep a finite stale sentinel so both the stale
            # and attention alerts fire rather than silently reporting age 0.
            candidate_ages.append(_OVERVIEW_UNTRUSTED_SNAPSHOT_AGE_SECONDS)
            attention_users.add(owner_user_id)
        else:
            candidate_ages.append(age)
        status = _bounded_label(str(row["source_status"]), _OVERVIEW_CARD_STATUSES)
        if status != "ok" or _overview_attention_required(row["attention_required"]):
            attention_users.add(owner_user_id)
    if "overview_refresh_card_states" in tables:
        card_columns = _columns(conn, "overview_refresh_card_states")
        if {"owner_user_id", "status"} <= card_columns:
            for row in conn.execute(
                "SELECT owner_user_id, status FROM overview_refresh_card_states"
            ).fetchall():
                owner_user_id = row["owner_user_id"]
                if not isinstance(owner_user_id, str) or owner_user_id not in tracked_users:
                    continue
                status = _bounded_label(str(row["status"]), _OVERVIEW_CARD_STATUSES)
                card_states[status] += 1
                if status != "ok":
                    attention_users.add(owner_user_id)
    return max(candidate_ages, default=0.0), missing, len(attention_users), card_states


def _active_user_ids(
    auth_path: Path,
    *,
    maintenance_read_only: bool = False,
) -> tuple[str, ...]:
    if not auth_path.is_file():
        return ()
    with closing(
        _maintenance_read_only(auth_path, source="auth")
        if maintenance_read_only
        else _read_only(auth_path)
    ) as conn:
        if "users" not in _tables(conn):
            return ()
        query = "SELECT id FROM users"
        if "status" in _columns(conn, "users"):
            query += " WHERE status = 'active'"
        rows = conn.execute(query).fetchall()
    return tuple(str(row["id"]) for row in rows if isinstance(row["id"], str))


def _literature_saga_metrics(
    path: Path,
    now: datetime,
    *,
    maintenance_read_only: bool = False,
) -> tuple[float, dict[str, int]]:
    counts = {status: 0 for status in _SAGA_STATUSES}
    if not path.is_file():
        return 0.0, counts
    with closing(
        _maintenance_read_only(path, source="literature")
        if maintenance_read_only
        else _read_only(path)
    ) as conn:
        if "literature_research_task_intents" not in _tables(conn):
            return 0.0, counts
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM literature_research_task_intents
            GROUP BY status
            """
        ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"])
        row = conn.execute(
            """
            SELECT MIN(created_at) AS oldest_created_at
            FROM literature_research_task_intents
            WHERE status IN ('pending', 'creating_task', 'task_created', 'retryable_failed')
            """
        ).fetchone()
    return _age_seconds(row["oldest_created_at"] if row is not None else None, now), counts


def _overview_job_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    counts = {status: 0 for status in _OVERVIEW_JOB_STATUSES}
    if "overview_refresh_jobs" not in tables:
        return counts
    for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM overview_refresh_jobs GROUP BY status"
    ).fetchall():
        status = str(row["status"])
        if status in counts:
            counts[status] = int(row["count"])
    return counts


def _age_seconds(value: object, now: datetime) -> float:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return 0.0
    return max(0.0, (now - parsed.astimezone(UTC)).total_seconds())


def _trusted_overview_age_seconds(value: object, now: datetime) -> float | None:
    """Return a valid Overview age, never treating invalid data as fresh."""

    parsed = _parse_timestamp(value)
    if parsed is None or parsed > now:
        return None
    return (now - parsed).total_seconds()


def _overview_attention_required(value: object) -> bool:
    """Treat malformed durable attention flags conservatively as attention."""

    return not (isinstance(value, int) and not isinstance(value, bool) and value == 0)


def _parse_timestamp(value: object | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _publish_collected_metrics(
    collected: _CollectedDomainMetrics,
    *,
    scrape_success: bool,
    last_success_timestamp: float,
    risk_state_known: bool,
    telemetry_delivery_failure_latched: bool,
    source_states: Mapping[str, str],
) -> None:
    snapshot = collected.snapshot
    risk_value = 1.0 if risk_state_known else math.nan

    def risk(value: float) -> float:
        return value if risk_state_known else risk_value

    _gauge("ainrf_domain_metrics_scrape_success", 1.0 if scrape_success else 0.0)
    _gauge("ainrf_domain_metrics_last_success_timestamp_seconds", last_success_timestamp)
    _gauge("ainrf_domain_metrics_risk_state_known", 1.0 if risk_state_known else 0.0)
    _gauge(
        "ainrf_domain_telemetry_delivery_failure_latched",
        1.0 if telemetry_delivery_failure_latched else 0.0,
    )
    for source in _TELEMETRY_SOURCES:
        current_state = source_states.get(source, "unavailable")
        for state in _TELEMETRY_SOURCE_STATES:
            _gauge(
                "ainrf_domain_telemetry_source_status",
                1.0 if current_state == state else 0.0,
                {"source": source, "state": state},
            )
    for state in _SUBMISSION_BACKLOG_STATES:
        _gauge(
            "ainrf_domain_turn_submission_entries",
            risk(float(collected.submission_backlog.get(state, 0))),
            {"state": state},
        )
    for status in _SAGA_STATUSES:
        _gauge(
            "ainrf_domain_literature_saga_intents",
            risk(float(collected.saga_counts.get(status, 0))),
            {"status": status},
        )
    for status in _OVERVIEW_JOB_STATUSES:
        _gauge(
            "ainrf_domain_overview_refresh_jobs",
            risk(float(collected.overview_job_counts.get(status, 0))),
            {"status": status},
        )
    for status in _OVERVIEW_CARD_STATUSES:
        _gauge(
            "ainrf_domain_overview_card_states",
            risk(float(collected.overview_card_states.get(status, 0))),
            {"status": status},
        )
    _gauge(
        "ainrf_domain_turn_submission_oldest_pending_age_seconds",
        risk(snapshot.submission_oldest_pending_age_seconds),
    )
    _gauge(
        "ainrf_domain_turn_submission_backlog",
        risk(float(snapshot.submission_backlog_count)),
    )
    _gauge(
        "ainrf_domain_idempotency_records",
        risk(float(snapshot.idempotency_record_count)),
    )
    _gauge(
        "ainrf_domain_literature_saga_oldest_pending_age_seconds",
        risk(snapshot.literature_pending_age_seconds),
    )
    _gauge(
        "ainrf_domain_overview_snapshot_oldest_age_seconds",
        risk(snapshot.overview_oldest_age_seconds),
    )
    _gauge(
        "ainrf_domain_overview_missing_active_users",
        risk(float(snapshot.overview_missing_active_user_count)),
    )
    _gauge(
        "ainrf_domain_overview_attention_required",
        risk(float(snapshot.overview_attention_required_count)),
    )
    for (name, labels), value in collected.durable_counters.items():
        _set_counter(name, value, dict(labels))
