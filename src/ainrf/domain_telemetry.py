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

_DOMAIN_MODES = ("legacy", "prepared", "v2", "unknown")
_RUNTIME_MODES = ("legacy", "validate", "v2", "unknown")
_ISSUE_SEVERITIES = ("blocking", "non_blocking")
_ISSUE_RESOLUTIONS = ("open", "resolved")
_MIGRATION_RUN_STATUSES = ("running", "completed", "interrupted", "stale", "unknown")
_MIGRATION_RECORD_STATUSES = ("imported", "skipped", "attention_needed", "unknown")
_MIGRATION_ATTENTION_RECORD_TYPES = (
    "environment",
    "project",
    "project_member",
    "runtime_checkpoint",
    "session",
    "session_attempt",
    "source",
    "task",
    "task_output",
    "task_relationship",
    "workspace",
    "other",
    "unknown",
)
_MIGRATION_ATTENTION_CATEGORIES = (
    "canonical_path_conflict",
    "collaborator_unmapped",
    "environment_alias_conflict",
    "environment_identity_conflict",
    "environment_owner_unmapped",
    "environment_registry_invalid",
    "legacy_environment_placeholder",
    "orphan_task_relationship",
    "owner_missing",
    "owner_unmapped",
    "primary_link_inactive",
    "primary_workspace_conflict",
    "primary_workspace_missing",
    "project_identity_conflict",
    "runtime_checkpoint_unmapped",
    "session_attempt_unmapped",
    "session_mapping_missing",
    "session_unmapped",
    "source_manifest_changed",
    "task_domain_mapping_invalid",
    "task_output_unmapped",
    "task_owner_unmapped",
    "workspace_environment_ambiguous",
    "workspace_environment_invalid",
    "workspace_environment_missing",
    "workspace_identity_conflict",
    "workspace_owner_unmapped",
    "workspace_path_invalid",
    "workspace_project_missing",
    "unclassified",
    "other",
    "unknown",
)
_OUTBOX_BACKLOG_STATES = (
    "pending",
    "expired_claimed",
    "expired_dispatched",
    "launch_unknown",
)
_IDEMPOTENCY_OUTCOMES = ("accepted", "missing", "invalid", "conflict", "reused", "stored", "other")
_LEGACY_WRITE_SOURCES = ("legacy_json", "legacy_session", "other")
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
_ORPHAN_REASONS = (
    "missing_task",
    "missing_context_snapshot",
    "queued_without_recoverable_dispatch",
)
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
_DEPRECATED_ROUTE_GROUPS = (
    "environments",
    "literature",
    "projects",
    "tasks",
    "workspaces",
    "other",
)
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
        "attempt_id",
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
        "run_id",
        "runtime_session_id",
        "scope",
        "source",
        "status",
        "task_id",
        "trigger",
        "user_id",
        "workspace_id",
    }
)
_TELEMETRY_STORE_FILENAME = "domain_telemetry.sqlite3"
_TELEMETRY_ANCHOR_FILENAME = "domain_telemetry_anchor.json"
_TELEMETRY_DELIVERY_FAILURE_LATCH_FILENAME = "domain_telemetry_delivery_failure.json"
_TELEMETRY_STORE_SCHEMA_VERSION = 2
_DURABLE_COUNTER_LABEL_VALUES: dict[str, dict[str, tuple[str, ...]]] = {
    "ainrf_deprecated_route_calls_total": {"route": _DEPRECATED_ROUTE_GROUPS},
    "ainrf_domain_idempotency_requests_total": {"outcome": _IDEMPOTENCY_OUTCOMES},
    "ainrf_domain_legacy_write_attempts_total": {"source": _LEGACY_WRITE_SOURCES},
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

_V2_DOMAIN_CONTRACT_VERSION = 2
_V2_MIN_SOURCE_SCHEMA_VERSION: dict[str, int] = {
    "agentic_researcher": 25,
    "auth": 7,
    "literature": 6,
}
_V2_CONTROL_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "_schema_version": ("database", "version"),
    "domain_cutover_state": (
        "singleton",
        "state",
        "contract_version",
        "schema_version",
        "cutover_epoch",
        "constraints_ready",
        "cutover_ready",
        "committed_at",
        "cutover_run_id",
        "artifact_sha",
        "artifact_contract_min",
        "artifact_contract_max",
        "artifact_schema_min",
        "artifact_schema_max",
        "backup_manifest_sha256",
        "backup_tree_sha256",
        "restore_evidence_sha256",
        "source_inventory_sha256",
        "preparation_digest",
    ),
    "domain_migration_issues": (
        "run_id",
        "category",
        "record_type",
        "severity",
        "resolution_status",
    ),
    "domain_migration_runs": ("run_id", "status"),
    "domain_migration_record_results": ("run_id", "record_type", "source_record_id", "status"),
    "tasks": ("task_id",),
    "agent_task_attempts": ("attempt_id", "task_id", "status", "context_snapshot_id"),
    "context_snapshots": ("context_snapshot_id",),
    "task_dispatch_outbox": (
        "task_id",
        "attempt_id",
        "status",
        "created_at",
        "next_attempt_at",
        "claim_expires_at",
        "claim_heartbeat_at",
        "updated_at",
        "launch_unknown_at",
    ),
    "domain_idempotency_requests": ("actor_user_id", "scope", "idempotency_key"),
}
_V2_AUTH_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
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
_V2_LITERATURE_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
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
_V2_OVERVIEW_SOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
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
_PUBLISHED_MIGRATION_ATTENTION_LABELS: set[tuple[str, str]] = set()


@dataclass(frozen=True, slots=True)
class DomainTelemetrySnapshot:
    """The durable values emitted during one Prometheus scrape."""

    mode: str
    contract_version: int
    migration_issue_count: int
    migration_attention_needed_count: int
    outbox_oldest_age_seconds: float
    outbox_backlog_count: int
    orphan_attempt_count: int
    idempotency_record_count: int
    literature_pending_age_seconds: float
    overview_oldest_age_seconds: float
    overview_missing_active_user_count: int
    overview_attention_required_count: int


@dataclass(frozen=True, slots=True)
class _CollectedDomainMetrics:
    """One complete, internally consistent durable scrape result."""

    snapshot: DomainTelemetrySnapshot
    migration_issues: Mapping[tuple[str, str], int]
    migration_runs: Mapping[str, int]
    migration_records: Mapping[str, int]
    migration_attention: Mapping[tuple[str, str], int]
    outbox_backlog: Mapping[str, int]
    orphan_attempts: Mapping[str, int]
    saga_counts: Mapping[str, int]
    overview_job_counts: Mapping[str, int]
    overview_card_states: Mapping[str, int]
    durable_counters: Mapping[DurableCounterKey, float]


class _TelemetryStoreError(RuntimeError):
    """A local durable telemetry store was unavailable or malformed."""


class _TelemetrySourceReadinessError(_TelemetryStoreError):
    """A v2 scrape lacks a required authoritative telemetry source."""

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


def domain_telemetry_state_root_for_path(path: str | Path) -> Path | None:
    """Resolve a state root for a runtime artifact without logging its path."""

    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return None
    for candidate in (resolved, *resolved.parents):
        if candidate.name == "runtime":
            return candidate.parent
    return None


def _counter(
    name: str,
    labels: Mapping[str, str] | None = None,
    *,
    durable: bool = False,
    state_root: Path | None = None,
) -> bool:
    """Increment a metric without allowing telemetry failures to break work."""

    try:
        from ainrf.api.routes.metrics import inc_counter

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
        from ainrf.api.routes.metrics import set_gauge

        set_gauge(name, value, dict(labels) if labels else None)
    except Exception:  # pragma: no cover - metrics must stay non-fatal
        _LOG.debug("domain_telemetry_gauge_unavailable", metric=name)


def _set_counter(name: str, value: float, labels: Mapping[str, str]) -> None:
    """Hydrate one API-process counter from a durable monotonic total."""

    try:
        from ainrf.api.routes.metrics import set_counter

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


def record_legacy_write_attempt(
    *,
    source: str,
    path: str | Path | None = None,
    state_root: Path | None = None,
) -> None:
    """Record a blocked attempt to alter a sealed legacy source."""

    normalized_source = _bounded_label(source, _LEGACY_WRITE_SOURCES)
    inferred_root = state_root or (
        domain_telemetry_state_root_for_path(path) if path is not None else None
    )
    _counter(
        "ainrf_domain_legacy_write_attempts_total",
        {"source": normalized_source},
        durable=True,
        state_root=inferred_root,
    )
    log_domain_event("domain_legacy_write_blocked", source=normalized_source, path=path)


def record_idempotency_event(
    outcome: str,
    *,
    scope: str | None = None,
    idempotency_key: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
    runtime_session_id: str | None = None,
    run_id: str | None = None,
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
        attempt_id=attempt_id,
        runtime_session_id=runtime_session_id,
        run_id=run_id,
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
        attempt_id=_correlation_id(request, response, "attempt_id"),
        runtime_session_id=_correlation_id(request, response, "runtime_session_id", "runtime_id"),
        run_id=_correlation_id(request, response, "run_id", "migration_run_id"),
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


def _deprecated_route_group(route: str) -> str:
    prefix = route.split(".", 1)[0]
    return prefix if prefix in _DEPRECATED_ROUTE_GROUPS else "other"


def record_deprecated_route(
    *, route: str, replacement: str, state_root: Path | None = None
) -> None:
    """Record a compatibility route once, with release-gate-safe labels."""

    route_group = _deprecated_route_group(route)
    _counter(
        "ainrf_deprecated_route_calls_total",
        {"route": route_group},
        durable=True,
        state_root=state_root,
    )
    log_domain_event(
        "domain_deprecated_route",
        route=route_group,
        replacement=replacement,
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
    attempt_id: str | None = None,
    runtime_session_id: str | None = None,
    run_id: str | None = None,
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
        attempt_id=attempt_id,
        runtime_session_id=runtime_session_id,
        run_id=run_id,
    )


def _snapshot_payload(collected: _CollectedDomainMetrics) -> str:
    snapshot = collected.snapshot
    payload = {
        "schema_version": _TELEMETRY_STORE_SCHEMA_VERSION,
        "snapshot": {
            "mode": snapshot.mode,
            "contract_version": snapshot.contract_version,
            "migration_issue_count": snapshot.migration_issue_count,
            "migration_attention_needed_count": snapshot.migration_attention_needed_count,
            "outbox_oldest_age_seconds": snapshot.outbox_oldest_age_seconds,
            "outbox_backlog_count": snapshot.outbox_backlog_count,
            "orphan_attempt_count": snapshot.orphan_attempt_count,
            "idempotency_record_count": snapshot.idempotency_record_count,
            "literature_pending_age_seconds": snapshot.literature_pending_age_seconds,
            "overview_oldest_age_seconds": snapshot.overview_oldest_age_seconds,
            "overview_missing_active_user_count": snapshot.overview_missing_active_user_count,
            "overview_attention_required_count": snapshot.overview_attention_required_count,
        },
        "migration_issues": [
            {"severity": severity, "resolution": resolution, "value": value}
            for (severity, resolution), value in sorted(collected.migration_issues.items())
        ],
        "migration_runs": [
            {"status": status, "value": value}
            for status, value in sorted(collected.migration_runs.items())
        ],
        "migration_records": [
            {"status": status, "value": value}
            for status, value in sorted(collected.migration_records.items())
        ],
        "migration_attention": [
            {"record_type": record_type, "category": category, "value": value}
            for (record_type, category), value in sorted(collected.migration_attention.items())
        ],
        "outbox_backlog": [
            {"status": status, "value": value}
            for status, value in sorted(collected.outbox_backlog.items())
        ],
        "orphan_attempts": [
            {"reason": reason, "value": value}
            for reason, value in sorted(collected.orphan_attempts.items())
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


def _bounded_pair_count_records(
    payload: Mapping[str, object],
    *,
    key: str,
    first_label_name: str,
    first_allowed: tuple[str, ...],
    second_label_name: str,
    second_allowed: tuple[str, ...],
) -> dict[tuple[str, str], int]:
    """Parse a bounded two-label gauge collection from a persisted snapshot."""

    records = payload.get(key)
    if not isinstance(records, list):
        raise _TelemetryStoreError(f"invalid snapshot {key}")
    values: dict[tuple[str, str], int] = {}
    for record in records:
        if not isinstance(record, dict) or not all(
            isinstance(item_key, str) for item_key in record
        ):
            raise _TelemetryStoreError(f"invalid snapshot {key}")
        typed_record = cast(dict[str, object], record)
        first = typed_record.get(first_label_name)
        second = typed_record.get(second_label_name)
        if (
            not isinstance(first, str)
            or not isinstance(second, str)
            or first not in first_allowed
            or second not in second_allowed
        ):
            raise _TelemetryStoreError(f"invalid snapshot {key}")
        pair = (first, second)
        if pair in values:
            raise _TelemetryStoreError(f"duplicate snapshot {key}")
        values[pair] = _non_negative_int(typed_record.get("value"), name=key)
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
    mode = typed_snapshot.get("mode")
    if not isinstance(mode, str) or mode not in _DOMAIN_MODES:
        raise _TelemetryStoreError("invalid snapshot mode")
    snapshot = DomainTelemetrySnapshot(
        mode=mode,
        contract_version=_non_negative_int(
            typed_snapshot.get("contract_version"), name="contract_version"
        ),
        migration_issue_count=_non_negative_int(
            typed_snapshot.get("migration_issue_count"), name="migration_issue_count"
        ),
        migration_attention_needed_count=_non_negative_int(
            typed_snapshot.get("migration_attention_needed_count"),
            name="migration_attention_needed_count",
        ),
        outbox_oldest_age_seconds=_non_negative_float(
            typed_snapshot.get("outbox_oldest_age_seconds"), name="outbox_oldest_age_seconds"
        ),
        outbox_backlog_count=_non_negative_int(
            typed_snapshot.get("outbox_backlog_count"), name="outbox_backlog_count"
        ),
        orphan_attempt_count=_non_negative_int(
            typed_snapshot.get("orphan_attempt_count"), name="orphan_attempt_count"
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
    migration_issues = {
        (severity, resolution): 0
        for severity in _ISSUE_SEVERITIES
        for resolution in _ISSUE_RESOLUTIONS
    }
    issue_records = typed_payload.get("migration_issues")
    if not isinstance(issue_records, list):
        raise _TelemetryStoreError("invalid snapshot migration_issues")
    seen_issues: set[tuple[str, str]] = set()
    for record in issue_records:
        if not isinstance(record, dict) or not all(
            isinstance(item_key, str) for item_key in record
        ):
            raise _TelemetryStoreError("invalid snapshot migration_issues")
        typed_record = cast(dict[str, object], record)
        severity = typed_record.get("severity")
        resolution = typed_record.get("resolution")
        if (
            not isinstance(severity, str)
            or not isinstance(resolution, str)
            or severity not in _ISSUE_SEVERITIES
            or resolution not in _ISSUE_RESOLUTIONS
        ):
            raise _TelemetryStoreError("invalid snapshot migration_issues")
        issue_key = (severity, resolution)
        if issue_key in seen_issues:
            raise _TelemetryStoreError("duplicate snapshot migration_issues")
        seen_issues.add(issue_key)
        migration_issues[issue_key] = _non_negative_int(
            typed_record.get("value"), name="migration_issues"
        )
    if seen_issues != set(migration_issues):
        raise _TelemetryStoreError("incomplete snapshot migration_issues")
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
        migration_issues=migration_issues,
        migration_runs=_bounded_count_records(
            typed_payload,
            key="migration_runs",
            label_name="status",
            allowed=_MIGRATION_RUN_STATUSES,
        ),
        migration_records=_bounded_count_records(
            typed_payload,
            key="migration_records",
            label_name="status",
            allowed=_MIGRATION_RECORD_STATUSES,
        ),
        migration_attention=_bounded_pair_count_records(
            typed_payload,
            key="migration_attention",
            first_label_name="record_type",
            first_allowed=_MIGRATION_ATTENTION_RECORD_TYPES,
            second_label_name="category",
            second_allowed=_MIGRATION_ATTENTION_CATEGORIES,
        ),
        outbox_backlog=_bounded_count_records(
            typed_payload,
            key="outbox_backlog",
            label_name="status",
            allowed=_OUTBOX_BACKLOG_STATES,
        ),
        orphan_attempts=_bounded_count_records(
            typed_payload,
            key="orphan_attempts",
            label_name="reason",
            allowed=_ORPHAN_REASONS,
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
    runtime_mode: str | None = None,
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
                    _V2_CONTROL_SOURCE_REQUIREMENTS,
                    database_name="agentic_researcher",
                    minimum_version=_V2_MIN_SOURCE_SCHEMA_VERSION["agentic_researcher"],
                )
                source_states["overview"] = _schema_state(
                    conn,
                    tables,
                    _V2_OVERVIEW_SOURCE_REQUIREMENTS,
                    database_name="agentic_researcher",
                    minimum_version=_V2_MIN_SOURCE_SCHEMA_VERSION["agentic_researcher"],
                )
                mode, contract_version = _cutover_state(conn, tables)
                source_states["auth"] = _external_source_state(
                    root / "runtime" / "auth.sqlite3",
                    _V2_AUTH_SOURCE_REQUIREMENTS,
                    source="auth",
                    database_name="auth",
                    minimum_version=_V2_MIN_SOURCE_SCHEMA_VERSION["auth"],
                    maintenance_read_only=effective_read_only,
                )
                source_states["literature"] = _external_source_state(
                    root / "runtime" / "literature.sqlite3",
                    _V2_LITERATURE_SOURCE_REQUIREMENTS,
                    source="literature",
                    database_name="literature",
                    minimum_version=_V2_MIN_SOURCE_SCHEMA_VERSION["literature"],
                    maintenance_read_only=effective_read_only,
                )
                if effective_read_only or runtime_mode == "v2" or mode == "v2":
                    if mode == "v2" and not _committed_v2_control_fuse_ready(conn):
                        source_states["control"] = "schema_invalid"
                    not_ready = _first_not_ready_source(source_states)
                    if not_ready is not None:
                        raise _TelemetrySourceReadinessError(*not_ready)
                migration_issues = _migration_issue_count(conn, tables)
                migration_runs = _migration_run_counts(conn, tables)
                migration_records = _migration_record_counts(conn, tables)
                migration_attention = _migration_attention_issue_counts(conn, tables)
                outbox_age, outbox_backlog = _outbox_metrics(conn, tables, now)
                orphan_attempts = _orphan_attempt_count(conn, tables)
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
        except (OSError, sqlite3.Error) as exc:
            # A v2 API cannot use cached risk gauges when the authoritative
            # control source itself is unreadable.  The source-state gauge is
            # deliberately bounded and contains no filesystem or SQLite detail.
            source_states["control"] = "unavailable"
            if runtime_mode == "v2":
                raise _TelemetrySourceReadinessError("control", "unavailable") from exc
            raise
        literature_age, saga_counts = _literature_saga_metrics(
            root / "runtime" / "literature.sqlite3",
            now,
            maintenance_read_only=effective_read_only,
        )
        durable_counters = {} if effective_read_only else _load_durable_counters(root)
        snapshot = DomainTelemetrySnapshot(
            mode=mode,
            contract_version=contract_version,
            migration_issue_count=sum(migration_issues.values()),
            migration_attention_needed_count=migration_records["attention_needed"],
            outbox_oldest_age_seconds=outbox_age,
            outbox_backlog_count=sum(outbox_backlog.values()),
            orphan_attempt_count=sum(orphan_attempts.values()),
            idempotency_record_count=idempotency_records,
            literature_pending_age_seconds=literature_age,
            overview_oldest_age_seconds=overview_age,
            overview_missing_active_user_count=overview_missing,
            overview_attention_required_count=overview_attention,
        )
        collected = _CollectedDomainMetrics(
            snapshot=snapshot,
            migration_issues=migration_issues,
            migration_runs=migration_runs,
            migration_records=migration_records,
            migration_attention=migration_attention,
            outbox_backlog=outbox_backlog,
            orphan_attempts=orphan_attempts,
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
        if isinstance(exc, _TelemetrySourceReadinessError):
            _publish_collected_metrics(
                empty,
                runtime_mode=runtime_mode,
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
                runtime_mode=runtime_mode,
                scrape_success=False,
                last_success_timestamp=math.nan,
                risk_state_known=False,
                telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
                source_states=source_states,
            )
            return empty.snapshot
        _publish_collected_metrics(
            collected,
            runtime_mode=runtime_mode,
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
        runtime_mode=runtime_mode,
        scrape_success=True,
        last_success_timestamp=now.timestamp(),
        risk_state_known=True,
        telemetry_delivery_failure_latched=_telemetry_delivery_failure_latched(root),
        source_states=source_states,
    )
    return collected.snapshot


def _empty_collected_metrics() -> _CollectedDomainMetrics:
    snapshot = DomainTelemetrySnapshot(
        mode="unknown",
        contract_version=0,
        migration_issue_count=0,
        migration_attention_needed_count=0,
        outbox_oldest_age_seconds=0.0,
        outbox_backlog_count=0,
        orphan_attempt_count=0,
        idempotency_record_count=0,
        literature_pending_age_seconds=0.0,
        overview_oldest_age_seconds=0.0,
        overview_missing_active_user_count=0,
        overview_attention_required_count=0,
    )
    return _CollectedDomainMetrics(
        snapshot=snapshot,
        migration_issues={
            (severity, resolution): 0
            for severity in _ISSUE_SEVERITIES
            for resolution in _ISSUE_RESOLUTIONS
        },
        migration_runs={status: 0 for status in _MIGRATION_RUN_STATUSES},
        migration_records={status: 0 for status in _MIGRATION_RECORD_STATUSES},
        migration_attention={},
        outbox_backlog={status: 0 for status in _OUTBOX_BACKLOG_STATES},
        orphan_attempts={reason: 0 for reason in _ORPHAN_REASONS},
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


def _committed_v2_control_fuse_ready(conn: sqlite3.Connection) -> bool:
    """Validate the durable v2 fuse before calling its source telemetry ready.

    The normal cutover controller enforces these invariants transactionally.
    Telemetry repeats only the bounded, local facts needed to reject a stale
    or manually damaged control row instead of letting a v2 scrape claim a
    healthy source from table shape alone.
    """

    row = conn.execute(
        """
        SELECT state, contract_version, schema_version, constraints_ready, cutover_ready,
               committed_at, cutover_run_id, artifact_sha, artifact_contract_min,
               artifact_contract_max, artifact_schema_min, artifact_schema_max,
               backup_manifest_sha256, backup_tree_sha256, restore_evidence_sha256,
               source_inventory_sha256, preparation_digest
        FROM domain_cutover_state
        WHERE singleton = 1
        """
    ).fetchone()
    if row is None or row["state"] != "v2":
        return False

    integers = (
        "contract_version",
        "schema_version",
        "constraints_ready",
        "cutover_ready",
        "artifact_contract_min",
        "artifact_contract_max",
        "artifact_schema_min",
        "artifact_schema_max",
    )
    if any(not isinstance(row[name], int) or isinstance(row[name], bool) for name in integers):
        return False
    if row["contract_version"] != _V2_DOMAIN_CONTRACT_VERSION:
        return False
    if row["constraints_ready"] != 1 or row["cutover_ready"] != 1:
        return False
    current_schema = conn.execute(
        "SELECT version FROM _schema_version WHERE database = 'agentic_researcher'"
    ).fetchone()
    if (
        current_schema is None
        or not isinstance(current_schema["version"], int)
        or isinstance(current_schema["version"], bool)
        or row["schema_version"] != current_schema["version"]
        or row["schema_version"] < _V2_MIN_SOURCE_SCHEMA_VERSION["agentic_researcher"]
    ):
        return False
    if not (
        row["artifact_contract_min"] <= row["contract_version"] <= row["artifact_contract_max"]
        and row["artifact_schema_min"] <= row["schema_version"] <= row["artifact_schema_max"]
    ):
        return False

    return all(
        isinstance(row[name], str) and bool(row[name])
        for name in (
            "committed_at",
            "cutover_run_id",
            "artifact_sha",
            "backup_manifest_sha256",
            "backup_tree_sha256",
            "restore_evidence_sha256",
            "source_inventory_sha256",
            "preparation_digest",
        )
    )


def _cutover_state(conn: sqlite3.Connection, tables: set[str]) -> tuple[str, int]:
    if "domain_cutover_state" not in tables:
        return "unknown", 0
    columns = _columns(conn, "domain_cutover_state")
    selected = ["state" if "state" in columns else "'legacy' AS state"]
    selected.append(
        "contract_version" if "contract_version" in columns else "1 AS contract_version"
    )
    row = conn.execute(
        f"SELECT {', '.join(selected)} FROM domain_cutover_state WHERE singleton = 1"
    ).fetchone()
    value = str(row["state"]) if row is not None and row["state"] is not None else "legacy"
    mode = value if value in _DOMAIN_MODES else "unknown"
    raw_contract_version = row["contract_version"] if row is not None else None
    contract_version = (
        raw_contract_version
        if isinstance(raw_contract_version, int)
        and not isinstance(raw_contract_version, bool)
        and raw_contract_version >= 0
        else 0
    )
    return mode, contract_version


def _migration_issue_count(
    conn: sqlite3.Connection, tables: set[str]
) -> dict[tuple[str, str], int]:
    values = {
        (severity, resolution): 0
        for severity in _ISSUE_SEVERITIES
        for resolution in _ISSUE_RESOLUTIONS
    }
    if "domain_migration_issues" not in tables:
        return values
    has_resolution = "resolution_status" in _columns(conn, "domain_migration_issues")
    query = (
        "SELECT severity, COALESCE(resolution_status, 'open') AS resolution, COUNT(*) AS count "
        "FROM domain_migration_issues GROUP BY severity, resolution"
        if has_resolution
        else "SELECT severity, 'open' AS resolution, COUNT(*) AS count FROM domain_migration_issues GROUP BY severity"
    )
    for row in conn.execute(query).fetchall():
        severity = str(row["severity"])
        resolution = str(row["resolution"])
        if severity in _ISSUE_SEVERITIES and resolution in _ISSUE_RESOLUTIONS:
            values[(severity, resolution)] = int(row["count"])
    return values


def _migration_run_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    """Return current durable migration runs with a bounded status label."""

    values = {status: 0 for status in _MIGRATION_RUN_STATUSES}
    if "domain_migration_runs" not in tables:
        return values
    for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM domain_migration_runs GROUP BY status"
    ).fetchall():
        raw_status = str(row["status"])
        status = raw_status if raw_status in values else "unknown"
        values[status] += int(row["count"])
    return values


def _migration_record_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    values = {status: 0 for status in _MIGRATION_RECORD_STATUSES}
    if "domain_migration_record_results" not in tables:
        return values
    for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM domain_migration_record_results GROUP BY status"
    ).fetchall():
        raw_status = str(row["status"])
        status = raw_status if raw_status in values else "unknown"
        values[status] += int(row["count"])
    return values


def _migration_attention_issue_counts(
    conn: sqlite3.Connection, tables: set[str]
) -> dict[tuple[str, str], int]:
    """Return unresolved migration remediation work with bounded labels.

    Import result rows preserve historical outcomes, including an
    ``attention_needed`` result after its remediation has been completed.
    The issue workflow is the authoritative current queue, so this gauge
    counts only open typed issues rather than joining and over-counting source
    records with multiple remediation steps.
    """

    if "domain_migration_issues" not in tables:
        return {}
    columns = _columns(conn, "domain_migration_issues")
    if not {"record_type", "category"} <= columns:
        return {}
    resolution = (
        "WHERE COALESCE(resolution_status, 'open') = 'open'"
        if "resolution_status" in columns
        else ""
    )
    values: dict[tuple[str, str], int] = {}
    query = (
        "SELECT record_type, category, COUNT(*) AS count "
        f"FROM domain_migration_issues {resolution} GROUP BY record_type, category"
    )
    for row in conn.execute(query).fetchall():
        record_type = _bounded_label(str(row["record_type"]), _MIGRATION_ATTENTION_RECORD_TYPES)
        category = _bounded_label(str(row["category"]), _MIGRATION_ATTENTION_CATEGORIES)
        key = (record_type, category)
        values[key] = values.get(key, 0) + int(row["count"])
    return values


def _outbox_metrics(
    conn: sqlite3.Connection,
    tables: set[str],
    now: datetime,
) -> tuple[float, dict[str, int]]:
    """Return only recoverable or uncertain dispatches, never normal runs.

    A ``dispatched`` row represents a running runtime until its lease expires.
    Counting it from ``created_at`` makes every legitimate long task fire the
    five-minute outbox alert.  Mirror dispatcher recovery eligibility instead:
    pending due work, expired claims, expired dispatch leases, and explicitly
    uncertain launches are backlog.
    """

    counts = {state: 0 for state in _OUTBOX_BACKLOG_STATES}
    if "task_dispatch_outbox" not in tables:
        return 0.0, counts
    columns = _columns(conn, "task_dispatch_outbox")
    selected = ["status", "created_at"]
    for column in (
        "next_attempt_at",
        "claim_expires_at",
        "claim_heartbeat_at",
        "updated_at",
        "launch_unknown_at",
    ):
        if column in columns:
            selected.append(column)
    rows = conn.execute(f"SELECT {', '.join(selected)} FROM task_dispatch_outbox").fetchall()
    ages: list[float] = []
    for row in rows:
        status = str(row["status"])
        state: str | None = None
        anchor: object = row["created_at"]
        if status == "pending" and _is_due(_row_value(row, "next_attempt_at"), now):
            state = "pending"
        elif status == "claimed" and _outbox_lease_is_stale(row, now):
            state = "expired_claimed"
            anchor = _outbox_staleness_anchor(row)
        elif status == "dispatched" and _outbox_lease_is_stale(row, now):
            state = "expired_dispatched"
            anchor = _outbox_staleness_anchor(row)
        elif status == "launch_unknown":
            state = "launch_unknown"
            anchor = _row_value(row, "launch_unknown_at") or _outbox_staleness_anchor(row)
        if state is not None:
            counts[state] += 1
            ages.append(_age_seconds(anchor, now))
    return max(ages, default=0.0), counts


def _row_value(row: sqlite3.Row, name: str) -> object | None:
    return row[name] if name in row.keys() else None


def _is_due(value: object | None, now: datetime) -> bool:
    if value is None:
        return True
    parsed = _parse_timestamp(value)
    return parsed is None or parsed <= now


def _outbox_lease_is_stale(row: sqlite3.Row, now: datetime) -> bool:
    expires_at = _row_value(row, "claim_expires_at")
    if expires_at is not None:
        return _is_due(expires_at, now)
    for field in ("claim_heartbeat_at", "updated_at", "created_at"):
        timestamp = _parse_timestamp(_row_value(row, field))
        if timestamp is not None:
            return (now - timestamp).total_seconds() >= 300
    return True


def _outbox_staleness_anchor(row: sqlite3.Row) -> object | None:
    for field in ("claim_expires_at", "claim_heartbeat_at", "updated_at", "created_at"):
        value = _row_value(row, field)
        if value is not None:
            return value
    return None


def _orphan_attempt_count(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    values = {reason: 0 for reason in _ORPHAN_REASONS}
    if "agent_task_attempts" not in tables:
        return values
    if "tasks" in tables:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_task_attempts AS attempt
            LEFT JOIN tasks AS task ON task.task_id = attempt.task_id
            WHERE task.task_id IS NULL
            """
        ).fetchone()
        values["missing_task"] = int(row["count"]) if row is not None else 0
    if "context_snapshots" in tables and "context_snapshot_id" in _columns(
        conn, "agent_task_attempts"
    ):
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_task_attempts AS attempt
            LEFT JOIN context_snapshots AS snapshot
              ON snapshot.context_snapshot_id = attempt.context_snapshot_id
            WHERE attempt.context_snapshot_id IS NOT NULL
              AND snapshot.context_snapshot_id IS NULL
            """
        ).fetchone()
        values["missing_context_snapshot"] = int(row["count"]) if row is not None else 0
    values["queued_without_recoverable_dispatch"] = (
        _queued_attempts_without_recoverable_dispatch_count(conn, tables)
    )
    return values


def _queued_attempts_without_recoverable_dispatch_count(
    conn: sqlite3.Connection, tables: set[str]
) -> int:
    """Count queued Attempts whose durable dispatch cannot make progress.

    A queued Attempt must retain a ``pending``, ``claimed``, or ``dispatched``
    outbox row.  Claims can expire and dispatched runtimes can be reconciled,
    so each remains recoverable.  A terminal row, a ``launch_unknown`` row,
    or no row at all leaves a queued Attempt stranded and needs operator
    remediation rather than a second blind Task launch.
    """

    attempt_columns = _columns(conn, "agent_task_attempts")
    if "status" not in attempt_columns:
        return 0
    if "task_dispatch_outbox" not in tables:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM agent_task_attempts WHERE status = 'queued'"
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    dispatch_columns = _columns(conn, "task_dispatch_outbox")
    if not {"attempt_id", "status"} <= dispatch_columns:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM agent_task_attempts WHERE status = 'queued'"
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    task_match = ""
    if "task_id" in dispatch_columns and "task_id" in attempt_columns:
        task_match = " AND dispatch.task_id = attempt.task_id"
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM agent_task_attempts AS attempt
        WHERE attempt.status = 'queued'
          AND NOT EXISTS (
              SELECT 1
              FROM task_dispatch_outbox AS dispatch
              WHERE dispatch.attempt_id = attempt.attempt_id{task_match}
                AND dispatch.status IN ('pending', 'claimed', 'dispatched')
          )
        """
    ).fetchone()
    return int(row["count"]) if row is not None else 0


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
    runtime_mode: str | None,
    scrape_success: bool,
    last_success_timestamp: float,
    risk_state_known: bool,
    telemetry_delivery_failure_latched: bool,
    source_states: Mapping[str, str],
) -> None:
    global _PUBLISHED_MIGRATION_ATTENTION_LABELS

    snapshot = collected.snapshot
    risk_value = 1.0 if risk_state_known else math.nan

    def risk(value: float) -> float:
        return value if risk_state_known else risk_value

    for mode in _DOMAIN_MODES:
        _gauge(
            "ainrf_domain_mode_info",
            risk(1.0 if snapshot.mode == mode else 0.0),
            {"mode": mode},
        )
    normalized_runtime_mode = _bounded_label(runtime_mode or "unknown", _RUNTIME_MODES)
    for mode in _RUNTIME_MODES:
        _gauge(
            "ainrf_domain_runtime_mode_info",
            1.0 if normalized_runtime_mode == mode else 0.0,
            {"mode": mode},
        )
    _gauge("ainrf_domain_contract_version", risk(float(snapshot.contract_version)))
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
    for severity in _ISSUE_SEVERITIES:
        for resolution in _ISSUE_RESOLUTIONS:
            value = collected.migration_issues.get((severity, resolution), 0)
            _gauge(
                "ainrf_domain_migration_issues",
                risk(float(value)),
                {"severity": severity, "resolution_status": resolution},
            )
    for status in _MIGRATION_RUN_STATUSES:
        _gauge(
            "ainrf_domain_migration_runs",
            risk(float(collected.migration_runs.get(status, 0))),
            {"status": status},
        )
    for status in _MIGRATION_RECORD_STATUSES:
        _gauge(
            "ainrf_domain_migration_record_results",
            risk(float(collected.migration_records.get(status, 0))),
            {"status": status},
        )
    attention_labels = set(collected.migration_attention) | _PUBLISHED_MIGRATION_ATTENTION_LABELS
    if not risk_state_known:
        attention_labels.add(("unknown", "unknown"))
    for record_type, category in sorted(attention_labels):
        _gauge(
            "ainrf_domain_migration_attention_needed_issues",
            risk(float(collected.migration_attention.get((record_type, category), 0))),
            {"record_type": record_type, "category": category},
        )
    _PUBLISHED_MIGRATION_ATTENTION_LABELS = attention_labels
    for state in _OUTBOX_BACKLOG_STATES:
        _gauge(
            "ainrf_domain_dispatch_outbox_entries",
            risk(float(collected.outbox_backlog.get(state, 0))),
            {"state": state},
        )
    for reason in _ORPHAN_REASONS:
        _gauge(
            "ainrf_domain_orphan_attempts",
            risk(float(collected.orphan_attempts.get(reason, 0))),
            {"reason": reason},
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
        "ainrf_domain_dispatch_outbox_oldest_age_seconds",
        risk(snapshot.outbox_oldest_age_seconds),
    )
    _gauge(
        "ainrf_domain_dispatch_outbox_backlog",
        risk(float(snapshot.outbox_backlog_count)),
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
