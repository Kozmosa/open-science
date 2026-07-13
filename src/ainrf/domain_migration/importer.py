"""Resumable, auditable import of legacy domain state into the v2 schema."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.environment_identity import (
    canonical_connection_json,
    canonical_connection_object,
    environment_connection_fingerprint,
)
from ainrf.domain.context import (
    context_version_fingerprint,
    empty_fragment_manifest_json,
    record_context_version_fragment_provenance_in_transaction,
    unresolved_legacy_fragment_provenance_evidence,
)
from ainrf.domain_migration.sources import SourceSnapshotSet, SourceStaleError

_ACTIVE_TASK_STATUSES = frozenset(
    {"pending", "queued", "starting", "running", "pausing", "cancelling"}
)
_TERMINAL_ATTEMPT_STATUSES = frozenset({"completed", "failed", "cancelled", "stopped"})


class MigrationInterruptedError(RuntimeError):
    """Raised only by the deterministic test interruption hook.

    Real process crashes naturally leave the most recently committed record
    result and checkpoint behind.  The hook gives the same durable state to
    tests without relying on a process kill.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Domain migration run {run_id} was interrupted")


@dataclass(frozen=True, slots=True)
class MigrationReport:
    run_id: str
    status: str
    imported_count: int
    skipped_count: int
    attention_needed_count: int
    blocking_issue_count: int
    cutover_allowed: bool
    phase: str = ""
    source_manifest_sha256: str | None = None
    artifact_sha: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MigrationInspection:
    run_id: str
    mode: str
    status: str
    phase: str
    checkpoint: dict[str, object]
    source_manifest_sha256: str | None
    artifact_sha: str | None
    heartbeat_at: str | None
    resume_metadata: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MigrationRecordResult:
    source_path: str
    record_type: str
    source_record_id: str
    source_payload_sha256: str
    status: str
    target_id: str | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    run_id: str
    counts: dict[str, int]
    blocking_issues: tuple[str, ...]
    non_blocking_issues: tuple[str, ...]
    cutover_allowed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkspaceEnvironmentInference:
    """One explicit outcome for legacy Workspace Environment inference."""

    environment_id: str | None
    detail: str
    candidates: tuple[str, ...] = ()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _as_record_id(value: object, *, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def _as_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _normalise_records(payload: object, *, id_field: str) -> list[dict[str, object]]:
    """Accept current ``items`` registries and old ID-to-record maps.

    A malformed registry must be a visible import failure, never an empty
    source.  This deliberately accepts the old map representation because a
    few pre-registry installations wrote that form.
    """

    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        payload_map = _as_record(payload)
        assert payload_map is not None
        items = payload_map.get("items")
        if items is not None:
            if not isinstance(items, list):
                raise ValueError("Legacy JSON field 'items' must be a list")
            raw_records = items
        else:
            raw_records = []
            for source_id, value in payload_map.items():
                item = _as_record(value)
                if item is None:
                    raise ValueError("Legacy JSON map values must be objects")
                item.setdefault(id_field, str(source_id))
                raw_records.append(item)
    else:
        raise ValueError("Legacy JSON source must be an object or list")
    records: list[dict[str, object]] = []
    for item in raw_records:
        record = _as_record(item)
        if record is None:
            raise ValueError("Legacy JSON records must be objects")
        records.append(record)
    return records


class DomainImporter:
    """Import one immutable source snapshot in resumable committed phases.

    The v2 database remains an additive shadow target in ``validate`` mode;
    neither mode writes a legacy JSON registry, session database, nor source
    SQLite file.  Every source record receives one durable terminal outcome
    before its transaction is committed, which makes a retry safe after a
    process crash.
    """

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._interrupt_after_records: int | None = None
        self._processed_records = 0
        self._current_phase = "initial"

    def run(
        self,
        *,
        mode: str = "validate",
        artifact_sha: str | None = None,
        resume_run_id: str | None = None,
        interrupt_after_records: int | None = None,
    ) -> MigrationReport:
        """Run or resume a shadow import from a fixed source snapshot.

        ``interrupt_after_records`` is intentionally a test-only fault
        injection point.  It interrupts after a source outcome was committed,
        exactly as an unexpected process exit would.
        """

        if mode not in {"validate", "apply"}:
            raise ValueError("mode must be validate or apply")
        if interrupt_after_records is not None and interrupt_after_records < 1:
            raise ValueError("interrupt_after_records must be positive")
        self._interrupt_after_records = interrupt_after_records
        self._processed_records = 0
        self._current_phase = "snapshot"
        effective_artifact = artifact_sha or "development"
        run_id: str | None = None
        try:
            # Capture source SQLite databases before creating/upgrading the
            # target because agentic_researcher.sqlite3 is both a legacy source
            # and the additive target.
            with SourceSnapshotSet(self._state_root) as sources:
                source_data = self._load_source_data(sources)
                manifest_json = self._manifest_json(sources, source_data)
                manifest_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
                self._runtime_root.mkdir(parents=True, exist_ok=True)
                with closing(connect(self._db_path)) as conn:
                    run_pending(conn, "agentic_researcher")
                    run_id, existing = self._start_or_resume_run(
                        conn,
                        mode=mode,
                        artifact_sha=effective_artifact,
                        manifest_json=manifest_json,
                        manifest_digest=manifest_digest,
                        resume_run_id=resume_run_id,
                    )
                    if existing:
                        return self._report(conn, run_id)
                    self._run_pipeline(conn, run_id, source_data)
                    # A snapshot gives us stable read data; this final source
                    # check prevents a changing JSON registry from being used
                    # to declare a cutover-ready run.
                    sources.verify_unchanged()
                    self._set_run_status(conn, run_id, status="completed", phase="completed")
                    self._refresh_counts(conn, run_id)
                    conn.commit()
                    return self._report(conn, run_id)
        except SourceStaleError as exc:
            if run_id is None:
                raise
            with closing(connect(self._db_path)) as conn:
                self._issue(
                    conn,
                    run_id,
                    category="source_manifest_changed",
                    record_type="source",
                    record_id="manifest",
                    detail=str(exc),
                    blocking=True,
                )
                self._set_run_status(conn, run_id, status="stale", phase="stale")
                self._refresh_counts(conn, run_id)
                conn.commit()
                return self._report(conn, run_id)
        except MigrationInterruptedError:
            raise
        except Exception as exc:
            if run_id is not None:
                with closing(connect(self._db_path)) as conn:
                    self._set_run_status(
                        conn,
                        run_id,
                        status="interrupted",
                        phase=self._current_phase,
                        error=str(exc),
                    )
                    self._refresh_counts(conn, run_id)
                    conn.commit()
            raise
        finally:
            self._interrupt_after_records = None

    def resume(self, run_id: str, *, artifact_sha: str | None = None) -> MigrationReport:
        inspection = self.inspect(run_id)
        return self.run(
            mode=inspection.mode,
            artifact_sha=artifact_sha or inspection.artifact_sha,
            resume_run_id=run_id,
        )

    def inspect(self, run_id: str) -> MigrationInspection:
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
            row = conn.execute(
                "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown domain migration run: {run_id}")
        return MigrationInspection(
            run_id=str(row["run_id"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
            phase=str(row["phase"]),
            checkpoint=self._json_object(row["checkpoint_json"]),
            source_manifest_sha256=self._optional_text(row["source_manifest_sha256"]),
            artifact_sha=self._optional_text(row["artifact_sha"]),
            heartbeat_at=self._optional_text(row["heartbeat_at"]),
            resume_metadata=self._json_object(row["resume_metadata_json"]),
        )

    def record_results(self, run_id: str) -> Iterable[MigrationRecordResult]:
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
            rows = conn.execute(
                """
                SELECT source_path, record_type, source_record_id, source_payload_sha256,
                       status, target_id, detail
                FROM domain_migration_record_results
                WHERE run_id = ?
                ORDER BY created_at, source_path, record_type, source_record_id
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            MigrationRecordResult(
                source_path=str(row["source_path"]),
                record_type=str(row["record_type"]),
                source_record_id=str(row["source_record_id"]),
                source_payload_sha256=str(row["source_payload_sha256"]),
                status=str(row["status"]),
                target_id=self._optional_text(row["target_id"]),
                detail=str(row["detail"]),
            )
            for row in rows
        )

    def reconcile(self, run_id: str | None = None) -> ReconciliationReport:
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
            if run_id is None:
                row = conn.execute(
                    "SELECT run_id FROM domain_migration_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    raise ValueError("No domain migration run exists")
                run_id = str(row["run_id"])
            run = conn.execute(
                "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"Unknown domain migration run: {run_id}")
            blockers = self._reconciliation_blockers(conn, run_id, run)
            counts = self._reconciliation_counts(conn, run_id)
            state = conn.execute(
                "SELECT constraints_ready FROM domain_cutover_state WHERE singleton = 1"
            ).fetchone()
            cutover_allowed = (
                str(run["status"]) == "completed"
                and not blockers
                and state is not None
                and bool(state["constraints_ready"])
            )
            conn.execute(
                "UPDATE domain_migration_runs SET cutover_allowed = ?, heartbeat_at = ? WHERE run_id = ?",
                (int(cutover_allowed), _now(), run_id),
            )
            conn.commit()
            non_blocking = tuple(
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT DISTINCT category FROM domain_migration_issues
                    WHERE run_id = ? AND severity = 'non_blocking'
                    ORDER BY category
                    """,
                    (run_id,),
                )
            )
            return ReconciliationReport(
                run_id=run_id,
                counts=counts,
                blocking_issues=tuple(blockers),
                non_blocking_issues=non_blocking,
                cutover_allowed=cutover_allowed,
            )

    def _start_or_resume_run(
        self,
        conn: sqlite3.Connection,
        *,
        mode: str,
        artifact_sha: str,
        manifest_json: str,
        manifest_digest: str,
        resume_run_id: str | None,
    ) -> tuple[str, bool]:
        if resume_run_id is not None:
            row = conn.execute(
                "SELECT * FROM domain_migration_runs WHERE run_id = ?", (resume_run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown domain migration run: {resume_run_id}")
            if str(row["status"]) != "interrupted":
                raise ValueError("Only an interrupted domain migration run can be resumed")
            if str(row["source_manifest_sha256"] or "") != manifest_digest:
                raise ValueError(
                    "Cannot resume: source manifest does not match the interrupted run"
                )
            if str(row["artifact_sha"] or "") != artifact_sha:
                raise ValueError("Cannot resume: artifact SHA does not match the interrupted run")
            conn.execute(
                """
                UPDATE domain_migration_runs
                SET status = 'running', heartbeat_at = ?, resume_metadata_json = ?
                WHERE run_id = ?
                """,
                (
                    _now(),
                    _canonical_json({"resumed_at": _now(), "resumed_from_phase": row["phase"]}),
                    resume_run_id,
                ),
            )
            conn.commit()
            return resume_run_id, False

        completed = conn.execute(
            """
            SELECT run_id FROM domain_migration_runs
            WHERE mode = ? AND status = 'completed' AND source_manifest_sha256 = ?
              AND artifact_sha = ?
            ORDER BY started_at DESC LIMIT 1
            """,
            (mode, manifest_digest, artifact_sha),
        ).fetchone()
        if completed is not None:
            return str(completed["run_id"]), True

        run_id = uuid4().hex
        now = _now()
        conn.execute(
            """
            INSERT INTO domain_migration_runs (
                run_id, mode, source_manifest_json, source_manifest_sha256, artifact_sha,
                code_version, status, phase, checkpoint_json, heartbeat_at,
                resume_metadata_json, started_at
            ) VALUES (?, ?, ?, ?, ?, 'domain-v2-resumable', 'running', 'snapshot', '{}', ?, '{}', ?)
            """,
            (run_id, mode, manifest_json, manifest_digest, artifact_sha, now, now),
        )
        conn.commit()
        return run_id, False

    def _run_pipeline(
        self, conn: sqlite3.Connection, run_id: str, source: dict[str, object]
    ) -> None:
        user_aliases, usernames = self._user_maps(source)
        self._enter_phase(conn, run_id, "environments")
        self._ensure_seed_environment(conn)
        self._import_environment_registry(conn, run_id, source, user_aliases)
        self._import_environment_placeholders(conn, run_id, source)
        self._complete_phase(conn, run_id, "environments")

        self._enter_phase(conn, run_id, "projects")
        self._import_projects(conn, run_id, source, user_aliases, usernames)
        self._import_project_members(conn, run_id, source, user_aliases)
        self._complete_phase(conn, run_id, "projects")

        self._enter_phase(conn, run_id, "workspaces")
        self._import_workspaces(conn, run_id, source, user_aliases)
        self._complete_phase(conn, run_id, "workspaces")

        self._enter_phase(conn, run_id, "tasks")
        self._import_tasks(conn, run_id, source, user_aliases)
        self._import_relationships(conn, run_id, source)
        self._complete_phase(conn, run_id, "tasks")

        self._enter_phase(conn, run_id, "sessions")
        self._import_task_sessions(conn, run_id, source)
        self._import_session_attempts(conn, run_id, source)
        self._apply_task_output_ranges(conn, run_id, source)
        self._import_json_sessions(conn, run_id, source)
        self._import_runtime_checkpoints(conn, run_id, source)
        self._complete_phase(conn, run_id, "sessions")

    def _load_source_data(self, sources: SourceSnapshotSet) -> dict[str, object]:
        projects = self._read_json_records(sources, "runtime/projects.json", "project_id")
        workspaces = self._read_json_records(sources, "runtime/workspaces.json", "workspace_id")
        environments = self._read_json_records(sources, "runtime/environments.json", "id")
        edges = self._read_json_records(sources, "runtime/task_edges.json", "edge_id")
        json_sessions = self._read_json_records(sources, "runtime/sessions.json", "session_id")
        checkpoints: list[tuple[str, dict[str, object]]] = []
        for file in sources.manifest.files:
            relative_path = file.relative_path
            if relative_path.startswith("session-states/") and relative_path.endswith(".json"):
                payload = sources.read_json(relative_path)
                checkpoint = _as_record(payload)
                if checkpoint is None:
                    raise ValueError(
                        f"Invalid checkpoint source {relative_path}: expected an object"
                    )
                checkpoints.append((relative_path, checkpoint))
        return {
            "projects": projects,
            "workspaces": workspaces,
            "environments": environments,
            "edges": edges,
            "json_sessions": json_sessions,
            "users": self._read_sqlite_rows(sources, "runtime/auth.sqlite3", "users"),
            "collaborators": self._read_sqlite_rows(
                sources, "runtime/auth.sqlite3", "project_collaborators"
            ),
            "tasks": self._read_sqlite_rows(sources, "runtime/agentic_researcher.sqlite3", "tasks"),
            "task_outputs": self._read_sqlite_rows(
                sources, "runtime/agentic_researcher.sqlite3", "task_outputs"
            ),
            "session_attempts": self._read_sqlite_rows(
                sources, "runtime/sessions.sqlite3", "task_attempts"
            ),
            "task_sessions": self._read_sqlite_rows(
                sources, "runtime/sessions.sqlite3", "task_sessions"
            ),
            "checkpoints": checkpoints,
        }

    @staticmethod
    def _manifest_json(sources: SourceSnapshotSet, source: Mapping[str, object]) -> str:
        """Return a stable identity that excludes a newly-created empty target.

        The agentic database is the target as well as a possible source.  A
        fresh state root has no historical Task database, but the first run
        creates one; treating that empty generated file as a new source would
        make an otherwise identical interrupted run impossible to resume.
        """

        canonical = sources.manifest.canonical_dict()
        files_value = canonical.get("files", [])
        files = cast(list[object], files_value) if isinstance(files_value, list) else []
        tasks = source.get("tasks", [])
        has_legacy_tasks = isinstance(tasks, list) and bool(tasks)
        if not has_legacy_tasks:
            filtered: list[object] = []
            for file in files:
                record = _as_record(file)
                if (
                    record is not None
                    and record.get("relative_path") == "runtime/agentic_researcher.sqlite3"
                ):
                    continue
                filtered.append(file)
            files = filtered
        return _canonical_json({"version": 1, "files": files})

    @staticmethod
    def _read_json_records(
        sources: SourceSnapshotSet, relative_path: str, id_field: str
    ) -> list[dict[str, object]]:
        try:
            return _normalise_records(sources.read_json(relative_path), id_field=id_field)
        except FileNotFoundError:
            return []

    @staticmethod
    def _read_sqlite_rows(
        sources: SourceSnapshotSet, relative_path: str, table: str
    ) -> list[dict[str, object]]:
        try:
            conn = sources.connect_sqlite(relative_path)
        except FileNotFoundError:
            return []
        with closing(conn):
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if exists is None:
                return []
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [{str(key): row[key] for key in row.keys()} for row in rows]

    @staticmethod
    def _user_maps(source: Mapping[str, object]) -> tuple[dict[str, str], dict[str, str]]:
        aliases: dict[str, str] = {}
        usernames: dict[str, str] = {}
        administrator_ids: list[str] = []
        rows = source.get("users", [])
        if not isinstance(rows, list):
            return aliases, usernames
        for row in rows:
            record = _as_record(row)
            if record is None:
                continue
            user_id = record.get("id")
            if not isinstance(user_id, str) or not user_id:
                continue
            aliases[user_id] = user_id
            username = record.get("username")
            if isinstance(username, str) and username:
                aliases[username] = user_id
                usernames[user_id] = username
            if record.get("role") == "admin":
                administrator_ids.append(user_id)
        if len(administrator_ids) == 1:
            # Some early registries stored the literal ``admin`` rather than
            # the auth row ID.  Map it only when it is unambiguous.
            aliases["admin"] = administrator_ids[0]
        return aliases, usernames

    def _ensure_seed_environment(self, conn: sqlite3.Connection) -> None:
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO environments (
                environment_id, alias, owner_user_id, display_name, description,
                connection_json, is_seed, status, created_at, updated_at
            ) VALUES ('env-localhost', 'localhost', NULL, 'Localhost',
                'Seed environment retained from legacy runtime', '{}', 1, 'active', ?, ?)
            """,
            (now, now),
        )
        conn.commit()

    def _import_environment_registry(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        user_aliases: Mapping[str, str],
    ) -> None:
        """Import non-seed Environment registrations without copying secrets.

        Legacy registries were process-local and could contain credentials in
        arbitrary fields.  Only the execution endpoint metadata and an
        explicit credential *reference* are eligible for the durable domain
        registry; raw credentials remain absent from both control-plane rows
        and remediation artifacts.
        """

        environments = source.get("environments", [])
        if not isinstance(environments, list):
            return
        source_path = "runtime/environments.json"
        for index, raw_item in enumerate(environments):
            item = _as_record(raw_item)
            if item is None:
                continue
            environment_id = self._legacy_environment_id(
                item, fallback=f"<missing-environment-{index}>"
            )
            if self._has_result(conn, run_id, source_path, "environment", environment_id):
                continue
            sanitized = self._redacted_environment_record(item)
            if not self._safe_environment_identifier(environment_id):
                detail = "Legacy Environment ID is not a safe stable identifier"
                self._issue(
                    conn,
                    run_id,
                    category="environment_registry_invalid",
                    record_type="environment",
                    record_id=environment_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=sanitized,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            raw_owner = item.get("owner_user_id")
            owner_id = user_aliases.get(str(raw_owner)) if raw_owner is not None else None
            if raw_owner is not None and owner_id is None:
                detail = "Environment owner cannot be mapped to a durable auth user"
                self._issue(
                    conn,
                    run_id,
                    category="environment_owner_unmapped",
                    record_type="environment",
                    record_id=environment_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=sanitized,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            try:
                connection = self._legacy_environment_connection(item)
                connection_json = canonical_connection_json(connection)
                connection_fingerprint = environment_connection_fingerprint(connection)
            except ValueError as exc:
                detail = f"Legacy Environment connection is invalid: {exc}"
                self._issue(
                    conn,
                    run_id,
                    category="environment_registry_invalid",
                    record_type="environment",
                    record_id=environment_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=sanitized,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue

            existing = conn.execute(
                "SELECT * FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
            if existing is not None:
                if environment_id == "env-localhost" and bool(existing["is_seed"]):
                    self._record_outcome(
                        conn,
                        run_id,
                        source_path=source_path,
                        record_type="environment",
                        source_record_id=environment_id,
                        payload=item,
                        status="skipped",
                        target_id=environment_id,
                        detail="fixed seed Environment remains authoritative",
                    )
                    continue
                existing_connection = self._connection_object(existing["connection_json"])
                existing_fingerprint = (
                    str(existing["connection_fingerprint"])
                    if existing["connection_fingerprint"] is not None
                    else environment_connection_fingerprint(existing_connection)
                )
                if existing_fingerprint != connection_fingerprint:
                    detail = "Environment ID is already bound to a different endpoint identity"
                    self._issue(
                        conn,
                        run_id,
                        category="environment_identity_conflict",
                        record_type="environment",
                        record_id=environment_id,
                        detail=detail,
                    )
                    self._archive(
                        conn,
                        run_id,
                        source_path=source_path,
                        record_type="environment",
                        source_record_id=environment_id,
                        payload=sanitized,
                        reason=detail,
                    )
                    self._record_outcome(
                        conn,
                        run_id,
                        source_path=source_path,
                        record_type="environment",
                        source_record_id=environment_id,
                        payload=item,
                        status="attention_needed",
                        detail=detail,
                    )
                    continue
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=item,
                    status="skipped",
                    target_id=environment_id,
                    detail="legacy Environment identity already imported",
                )
                continue

            alias = self._optional_text(item.get("alias"))
            if alias is None:
                alias = f"legacy-{hashlib.sha256(environment_id.encode()).hexdigest()[:12]}"
            alias_row = conn.execute(
                "SELECT environment_id FROM environments WHERE alias = ?", (alias,)
            ).fetchone()
            if alias_row is not None:
                detail = "Legacy Environment alias conflicts with another durable Environment"
                self._issue(
                    conn,
                    run_id,
                    category="environment_alias_conflict",
                    record_type="environment",
                    record_id=environment_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=sanitized,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="environment",
                    source_record_id=environment_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            now = _now()
            source_status = self._optional_text(item.get("status"))
            status = "disabled" if source_status == "disabled" else "active"
            credential_ref = self._optional_text(
                item.get("credential_ref", item.get("credential_profile_ref"))
            )
            conn.execute(
                """
                INSERT INTO environments (
                    environment_id, alias, owner_user_id, display_name, description,
                    connection_json, connection_fingerprint, credential_ref, is_seed,
                    status, disabled_at, disabled_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    environment_id,
                    alias,
                    owner_id,
                    self._optional_text(item.get("display_name"))
                    or f"Legacy environment {environment_id}",
                    self._optional_text(item.get("description")),
                    connection_json,
                    connection_fingerprint,
                    credential_ref,
                    status,
                    now if status == "disabled" else None,
                    "disabled in legacy registry" if status == "disabled" else None,
                    self._source_time(item.get("created_at")),
                    self._source_time(item.get("updated_at")),
                ),
            )
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="environment",
                source_record_id=environment_id,
                payload=item,
                status="imported",
                target_id=environment_id,
                detail="imported non-seed legacy Environment without credential material",
            )

    @staticmethod
    def _legacy_environment_id(item: Mapping[str, object], *, fallback: str) -> str:
        value = item.get("environment_id", item.get("id"))
        return _as_record_id(value, fallback=fallback)

    @staticmethod
    def _safe_environment_identifier(environment_id: str) -> bool:
        return (
            bool(environment_id)
            and environment_id not in {".", ".."}
            and "/" not in environment_id
            and "\\" not in environment_id
            and "\x00" not in environment_id
        )

    @staticmethod
    def _connection_object(value: object) -> dict[str, object]:
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): item for key, item in parsed.items()}

    @staticmethod
    def _legacy_environment_connection(item: Mapping[str, object]) -> dict[str, object]:
        nested_value = item.get("connection")
        nested: dict[str, object]
        if isinstance(nested_value, Mapping):
            nested = {str(key): value for key, value in nested_value.items()}
        else:
            raw_json = item.get("connection_json")
            if isinstance(raw_json, str):
                try:
                    parsed = json.loads(raw_json)
                except json.JSONDecodeError:
                    parsed = None
                nested = (
                    {str(key): value for key, value in parsed.items()}
                    if isinstance(parsed, dict)
                    else {}
                )
            else:
                nested = {}
        connection: dict[str, object] = {}
        for field in (
            "host",
            "port",
            "user",
            "auth_kind",
            "identity_file",
            "proxy_jump",
            "proxy_command",
            "default_workdir",
            "preferred_python",
            "preferred_env_manager",
            "preferred_runtime_notes",
            "task_harness_profile",
            "tags",
        ):
            value = nested.get(field)
            if value is None:
                value = item.get(field)
            if value is not None:
                connection[field] = value
        ssh_options = nested.get("ssh_options")
        if ssh_options is None:
            ssh_options = item.get("ssh_options")
        if isinstance(ssh_options, Mapping):
            connection["ssh_options"] = {str(key): str(value) for key, value in ssh_options.items()}
        return canonical_connection_object(connection)

    @staticmethod
    def _redacted_environment_record(item: Mapping[str, object]) -> dict[str, object]:
        """Keep a remediation artifact useful while excluding credential values."""

        allowed = {
            "id",
            "environment_id",
            "alias",
            "owner_user_id",
            "display_name",
            "description",
            "status",
            "credential_ref",
            "credential_profile_ref",
            "created_at",
            "updated_at",
        }
        result = {str(key): value for key, value in item.items() if key in allowed}
        result["connection"] = DomainImporter._legacy_environment_connection(item)
        return result

    def _import_environment_placeholders(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        environment_statuses: dict[str, set[str]] = defaultdict(set)
        tasks = source.get("tasks", [])
        if isinstance(tasks, list):
            for task in tasks:
                record = _as_record(task)
                if record is None:
                    continue
                environment_id = record.get("environment_id")
                if isinstance(environment_id, str) and environment_id:
                    status = record.get("status")
                    environment_statuses[environment_id].add(
                        str(status) if status is not None else "unknown"
                    )
        projects = source.get("projects", [])
        if isinstance(projects, list):
            for project in projects:
                record = _as_record(project)
                if record is not None:
                    environment_id = record.get("default_environment_id")
                    if isinstance(environment_id, str) and environment_id:
                        environment_statuses.setdefault(environment_id, set())
        workspaces = source.get("workspaces", [])
        if isinstance(workspaces, list):
            for workspace in workspaces:
                record = _as_record(workspace)
                if record is None:
                    continue
                environment_id = record.get("environment_id")
                if isinstance(environment_id, str) and environment_id:
                    environment_statuses.setdefault(environment_id, set())
        for environment_id, statuses in sorted(environment_statuses.items()):
            if environment_id == "env-localhost":
                continue
            if not self._safe_environment_identifier(environment_id):
                self._issue(
                    conn,
                    run_id,
                    category="environment_registry_invalid",
                    record_type="environment",
                    record_id=environment_id,
                    detail="Historical Environment reference has an unsafe identifier",
                    blocking=bool(statuses & _ACTIVE_TASK_STATUSES),
                )
                continue
            existing = conn.execute(
                "SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)
            ).fetchone()
            if existing is None:
                alias = f"legacy-{hashlib.sha256(environment_id.encode()).hexdigest()[:12]}"
                now = _now()
                connection = {"legacy_placeholder": True}
                conn.execute(
                    """
                    INSERT INTO environments (
                        environment_id, alias, owner_user_id, display_name, description,
                        connection_json, connection_fingerprint, is_seed, status,
                        disabled_at, disabled_reason, created_at, updated_at
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, 0, 'disabled', ?,
                        'legacy environment registration was not found', ?, ?)
                    """,
                    (
                        environment_id,
                        alias,
                        f"Legacy environment {environment_id}",
                        "Placeholder created without copying credential material",
                        canonical_connection_json(connection),
                        environment_connection_fingerprint(connection),
                        now,
                        now,
                        now,
                    ),
                )
            blocking = bool(statuses & _ACTIVE_TASK_STATUSES)
            self._issue(
                conn,
                run_id,
                category="legacy_environment_placeholder",
                record_type="environment",
                record_id=environment_id,
                detail="Historical environment has no durable registration",
                blocking=blocking,
            )
        conn.commit()

    def _import_projects(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        user_aliases: Mapping[str, str],
        usernames: Mapping[str, str],
    ) -> None:
        projects = source.get("projects", [])
        if not isinstance(projects, list):
            return
        for index, item in enumerate(projects):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            project_id = _as_record_id(
                item.get("project_id"), fallback=f"<missing-project-{index}>"
            )
            if self._has_result(conn, run_id, "runtime/projects.json", "project", project_id):
                continue
            raw_owner = item.get("owner_user_id")
            owner_id = user_aliases.get(str(raw_owner)) if raw_owner is not None else None
            if owner_id is None:
                detail = "Project owner cannot be mapped to a durable auth user"
                self._issue(
                    conn,
                    run_id,
                    category="owner_unmapped",
                    record_type="project",
                    record_id=project_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/projects.json",
                    record_type="project",
                    source_record_id=project_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/projects.json",
                    record_type="project",
                    source_record_id=project_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            is_default = self._is_default_project(item, project_id, owner_id, usernames)
            existing = conn.execute(
                "SELECT project_id FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            try:
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO projects (
                            project_id, owner_user_id, name, description, status, is_default,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                        """,
                        (
                            project_id,
                            owner_id,
                            str(item.get("name", project_id)),
                            self._optional_text(item.get("description")),
                            int(is_default),
                            self._source_time(item.get("created_at")),
                            self._source_time(item.get("updated_at")),
                        ),
                    )
                    status = "imported"
                else:
                    status = "skipped"
                self._ensure_legacy_context(conn, project_id, owner_id)
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/projects.json",
                    record_type="project",
                    source_record_id=project_id,
                    payload=item,
                    status=status,
                    target_id=project_id,
                    detail="retained legacy project ID",
                )
            except sqlite3.IntegrityError as exc:
                detail = f"Project conflicts with an existing default/identity: {exc}"
                self._issue(
                    conn,
                    run_id,
                    category="project_identity_conflict",
                    record_type="project",
                    record_id=project_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/projects.json",
                    record_type="project",
                    source_record_id=project_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/projects.json",
                    record_type="project",
                    source_record_id=project_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )

    @staticmethod
    def _is_default_project(
        item: Mapping[str, object],
        project_id: str,
        owner_id: str,
        usernames: Mapping[str, str],
    ) -> bool:
        if item.get("is_default") is True:
            return True
        if project_id == "default":
            return True
        username = usernames.get(owner_id)
        return username is not None and project_id == f"{username}_default"

    def _ensure_legacy_context(
        self, conn: sqlite3.Connection, project_id: str, owner_id: str
    ) -> str:
        version_id = f"legacy-empty-{project_id}"
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_drafts
                (project_id, content, updated_by_user_id, updated_at)
            VALUES (?, '', ?, ?)
            """,
            (project_id, owner_id, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_versions
                (context_version_id, project_id, content, fingerprint, fragment_manifest_json,
                 is_active, created_by_user_id, created_at)
            VALUES (?, ?, '', ?, ?, 1, ?, ?)
            """,
            (
                version_id,
                project_id,
                context_version_fingerprint(""),
                empty_fragment_manifest_json(),
                owner_id,
                now,
            ),
        )
        provenance_row = conn.execute(
            """
            SELECT 1 FROM project_context_version_provenance
            WHERE context_version_id = ?
            """,
            (version_id,),
        ).fetchone()
        if provenance_row is None:
            record_context_version_fragment_provenance_in_transaction(
                conn,
                context_version_id=version_id,
                status="attention_needed",
                evidence_json=unresolved_legacy_fragment_provenance_evidence(
                    source="domain_importer.synthetic_legacy_context"
                ),
                recorded_at=now,
            )
        return version_id

    def _import_project_members(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        user_aliases: Mapping[str, str],
    ) -> None:
        collaborators = source.get("collaborators", [])
        if not isinstance(collaborators, list):
            return
        for index, item in enumerate(collaborators):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            project_id = _as_record_id(
                item.get("project_id"), fallback=f"<missing-project-{index}>"
            )
            raw_user = item.get("user_id")
            user_id = user_aliases.get(str(raw_user)) if raw_user is not None else None
            record_id = f"{project_id}:{raw_user or f'<missing-{index}>'}"
            source_path = "runtime/auth.sqlite3#project_collaborators"
            if self._has_result(conn, run_id, source_path, "project_member", record_id):
                continue
            project = conn.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None or user_id is None:
                detail = (
                    "Project collaborator cannot be mapped to an imported project and auth user"
                )
                self._issue(
                    conn,
                    run_id,
                    category="collaborator_unmapped",
                    record_type="project_member",
                    record_id=record_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="project_member",
                    source_record_id=record_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="project_member",
                    source_record_id=record_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            role = "editor" if item.get("role") == "editor" else "viewer"
            existing = conn.execute(
                "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if existing is None:
                now = _now()
                conn.execute(
                    """
                    INSERT INTO project_members
                        (project_id, user_id, role, can_publish, created_at, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (project_id, user_id, role, now, now),
                )
                status = "imported"
            else:
                status = "skipped"
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="project_member",
                source_record_id=record_id,
                payload=item,
                status=status,
                target_id=f"{project_id}:{user_id}",
                detail=f"legacy collaborator normalized to {role}",
            )

    def _import_workspaces(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        user_aliases: Mapping[str, str],
    ) -> None:
        workspaces = source.get("workspaces", [])
        if not isinstance(workspaces, list):
            return
        task_environments = self._task_environment_candidates(source)
        project_defaults = self._project_default_environments(source)
        project_primary = self._project_default_workspaces(source)
        active_workspace_ids = self._active_workspace_ids(source)
        known_environment_ids = self._known_environment_ids(conn)
        for index, item in enumerate(workspaces):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            workspace_id = _as_record_id(
                item.get("workspace_id"), fallback=f"<missing-workspace-{index}>"
            )
            if self._has_result(conn, run_id, "runtime/workspaces.json", "workspace", workspace_id):
                continue
            raw_owner = item.get("owner_user_id")
            owner_id = user_aliases.get(str(raw_owner)) if raw_owner is not None else None
            project_id = self._optional_text(item.get("project_id"))
            path = item.get("default_workdir")
            if owner_id is None:
                detail = "Workspace owner cannot be mapped to a durable auth user"
                self._issue(
                    conn,
                    run_id,
                    category="workspace_owner_unmapped",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            if not isinstance(path, str) or not Path(path).is_absolute():
                detail = "Workspace absolute canonical path cannot be inferred"
                self._issue(
                    conn,
                    run_id,
                    category="workspace_path_invalid",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            canonical_path = str(Path(path).expanduser().resolve())
            inference = self._workspace_environment_inference(
                item,
                project_id,
                workspace_id,
                task_environments,
                project_defaults,
                known_environment_ids,
            )
            is_active_workspace = workspace_id in active_workspace_ids
            attention_details: list[str] = []
            if inference.environment_id is None:
                environment_id = self._unresolved_workspace_environment_id(workspace_id)
                self._ensure_unresolved_workspace_placeholder(conn, environment_id)
                detail = inference.detail
                self._issue(
                    conn,
                    run_id,
                    category="workspace_environment_ambiguous",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail=detail,
                    blocking=is_active_workspace,
                )
                attention_details.append(detail)
            else:
                environment_id = inference.environment_id
                environment = conn.execute(
                    "SELECT status FROM environments WHERE environment_id = ?", (environment_id,)
                ).fetchone()
                if environment is None:
                    self._ensure_legacy_environment(
                        conn, run_id, environment_id, blocking=is_active_workspace
                    )
                    detail = "Workspace Environment has no durable registration"
                    self._issue(
                        conn,
                        run_id,
                        category="workspace_environment_missing",
                        record_type="workspace",
                        record_id=workspace_id,
                        detail=detail,
                        blocking=is_active_workspace,
                    )
                    attention_details.append(detail)
                elif str(environment["status"]) != "active":
                    detail = "Workspace derives a disabled Environment"
                    self._issue(
                        conn,
                        run_id,
                        category="workspace_environment_invalid",
                        record_type="workspace",
                        record_id=workspace_id,
                        detail=detail,
                        blocking=is_active_workspace,
                    )
                    attention_details.append(detail)
            project_exists = (
                conn.execute(
                    "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
                ).fetchone()
                if project_id is not None
                else True
            )
            if not project_exists:
                detail = "Workspace legacy Project was not imported"
                self._issue(
                    conn,
                    run_id,
                    category="workspace_project_missing",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail=detail,
                )
                attention_details.append(detail)
            try:
                existing = conn.execute(
                    "SELECT owner_user_id, environment_id, canonical_path FROM workspaces "
                    "WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
                if existing is None:
                    now = _now()
                    conn.execute(
                        """
                        INSERT INTO workspaces (
                            workspace_id, owner_user_id, environment_id, canonical_path, label,
                            description, workspace_context, legacy_project_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            workspace_id,
                            owner_id,
                            environment_id,
                            canonical_path,
                            str(item.get("label", workspace_id)),
                            self._optional_text(item.get("description")),
                            self._optional_text(item.get("workspace_prompt")),
                            project_id,
                            now,
                            now,
                        ),
                    )
                    status = "imported"
                else:
                    if (
                        str(existing["owner_user_id"]) != owner_id
                        or str(existing["environment_id"]) != environment_id
                        or str(existing["canonical_path"]) != canonical_path
                    ):
                        detail = "Workspace ID already maps to a different durable identity"
                        self._issue(
                            conn,
                            run_id,
                            category="workspace_identity_conflict",
                            record_type="workspace",
                            record_id=workspace_id,
                            detail=detail,
                        )
                        attention_details.append(detail)
                    else:
                        status = "skipped"
                if project_id is not None and project_exists:
                    self._link_legacy_workspace(
                        conn,
                        run_id,
                        project_id=project_id,
                        workspace_id=workspace_id,
                        owner_id=owner_id,
                        make_primary=bool(
                            item.get("is_primary") is True
                            or project_primary.get(project_id) == workspace_id
                            or workspace_id == "workspace-default"
                        ),
                    )
                if attention_details:
                    detail = "; ".join(sorted(set(attention_details)))
                    self._archive(
                        conn,
                        run_id,
                        source_path="runtime/workspaces.json",
                        record_type="workspace",
                        source_record_id=workspace_id,
                        payload=item,
                        reason=detail,
                    )
                    status = "attention_needed"
                else:
                    detail = "retained legacy workspace ID"
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    status=status,
                    target_id=workspace_id,
                    detail=detail,
                )
            except sqlite3.IntegrityError as exc:
                detail = f"Workspace canonical identity conflicts with existing state: {exc}"
                self._issue(
                    conn,
                    run_id,
                    category="canonical_path_conflict",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail=detail,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/workspaces.json",
                    record_type="workspace",
                    source_record_id=workspace_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )

    @staticmethod
    def _task_environment_candidates(source: Mapping[str, object]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        tasks = source.get("tasks", [])
        if not isinstance(tasks, list):
            return result
        for task in tasks:
            record = _as_record(task)
            if record is None:
                continue
            workspace_id = record.get("workspace_id")
            environment_id = record.get("environment_id")
            if isinstance(workspace_id, str) and isinstance(environment_id, str):
                result[workspace_id].add(environment_id)
        return result

    @staticmethod
    def _active_workspace_ids(source: Mapping[str, object]) -> set[str]:
        active: set[str] = set()
        tasks = source.get("tasks", [])
        if not isinstance(tasks, list):
            return active
        for task in tasks:
            record = _as_record(task)
            if record is None:
                continue
            workspace_id = record.get("workspace_id")
            if (
                isinstance(workspace_id, str)
                and str(record.get("status", "unknown")) in _ACTIVE_TASK_STATUSES
            ):
                active.add(workspace_id)
        return active

    @staticmethod
    def _known_environment_ids(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row["environment_id"])
            for row in conn.execute("SELECT environment_id FROM environments").fetchall()
        }

    @staticmethod
    def _project_default_environments(source: Mapping[str, object]) -> dict[str, str]:
        result: dict[str, str] = {}
        projects = source.get("projects", [])
        if not isinstance(projects, list):
            return result
        for project in projects:
            record = _as_record(project)
            if record is None:
                continue
            project_id = record.get("project_id")
            environment_id = record.get("default_environment_id")
            if isinstance(project_id, str) and isinstance(environment_id, str) and environment_id:
                result[project_id] = environment_id
        return result

    @staticmethod
    def _project_default_workspaces(source: Mapping[str, object]) -> dict[str, str]:
        result: dict[str, str] = {}
        projects = source.get("projects", [])
        if not isinstance(projects, list):
            return result
        for project in projects:
            record = _as_record(project)
            if record is None:
                continue
            project_id = record.get("project_id")
            workspace_id = record.get("default_workspace_id")
            if isinstance(project_id, str) and isinstance(workspace_id, str) and workspace_id:
                result[project_id] = workspace_id
        return result

    @staticmethod
    def _workspace_environment_inference(
        item: Mapping[str, object],
        project_id: str | None,
        workspace_id: str,
        task_environments: Mapping[str, set[str]],
        project_defaults: Mapping[str, str],
        known_environment_ids: set[str],
    ) -> WorkspaceEnvironmentInference:
        explicit = item.get("environment_id")
        candidates = set(task_environments.get(workspace_id, set()))
        if project_id is not None and project_id in project_defaults:
            candidates.add(project_defaults[project_id])
        if isinstance(explicit, str) and explicit:
            if candidates and candidates != {explicit}:
                return WorkspaceEnvironmentInference(
                    environment_id=None,
                    detail="Workspace explicit Environment conflicts with Task or Project evidence",
                    candidates=tuple(sorted(candidates.union({explicit}))),
                )
            return WorkspaceEnvironmentInference(
                environment_id=explicit,
                detail="Workspace declared an explicit Environment",
                candidates=(explicit,),
            )
        if len(candidates) == 1:
            environment_id = next(iter(candidates))
            return WorkspaceEnvironmentInference(
                environment_id=environment_id,
                detail="Workspace Environment inferred from one durable legacy reference",
                candidates=(environment_id,),
            )
        if len(candidates) > 1:
            return WorkspaceEnvironmentInference(
                environment_id=None,
                detail="Workspace has multiple possible Environment mappings",
                candidates=tuple(sorted(candidates)),
            )
        if known_environment_ids == {"env-localhost"}:
            return WorkspaceEnvironmentInference(
                environment_id="env-localhost",
                detail="Workspace Environment inferred from the only registered seed",
                candidates=("env-localhost",),
            )
        return WorkspaceEnvironmentInference(
            environment_id=None,
            detail="Workspace Environment cannot be uniquely inferred",
        )

    @staticmethod
    def _unresolved_workspace_environment_id(workspace_id: str) -> str:
        digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:16]
        return f"legacy-unresolved-workspace-{digest}"

    @staticmethod
    def _ensure_unresolved_workspace_placeholder(
        conn: sqlite3.Connection, environment_id: str
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)
        ).fetchone()
        if existing is not None:
            return
        now = _now()
        connection = {"legacy_unresolved_workspace_environment": True}
        conn.execute(
            """
            INSERT INTO environments (
                environment_id, alias, display_name, description, connection_json,
                connection_fingerprint, status, disabled_at, disabled_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'disabled', ?, ?, ?, ?)
            """,
            (
                environment_id,
                f"legacy-{hashlib.sha256(environment_id.encode()).hexdigest()[:12]}",
                "Unresolved legacy Workspace Environment",
                "Placeholder created because Workspace Environment inference was ambiguous",
                canonical_connection_json(connection),
                environment_connection_fingerprint(connection),
                now,
                "Workspace Environment requires an explicit reconciliation decision",
                now,
                now,
            ),
        )

    def _ensure_legacy_environment(
        self, conn: sqlite3.Connection, run_id: str, environment_id: str, *, blocking: bool
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)
        ).fetchone()
        if existing is None:
            now = _now()
            connection = {"legacy_placeholder": True}
            conn.execute(
                """
                INSERT INTO environments (
                    environment_id, alias, display_name, description, connection_json,
                    connection_fingerprint, status, disabled_at, disabled_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'disabled', ?,
                    'legacy environment registration was not found', ?, ?)
                """,
                (
                    environment_id,
                    f"legacy-{hashlib.sha256(environment_id.encode()).hexdigest()[:12]}",
                    f"Legacy environment {environment_id}",
                    "Placeholder created without copying credential material",
                    canonical_connection_json(connection),
                    environment_connection_fingerprint(connection),
                    now,
                    now,
                    now,
                ),
            )
        self._issue(
            conn,
            run_id,
            category="legacy_environment_placeholder",
            record_type="environment",
            record_id=environment_id,
            detail="Historical environment has no durable registration",
            blocking=blocking,
        )

    def _link_legacy_workspace(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        make_primary: bool,
    ) -> None:
        project = conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if project is None:
            self._issue(
                conn,
                run_id,
                category="workspace_project_missing",
                record_type="workspace",
                record_id=workspace_id,
                detail="Workspace legacy project was not imported",
            )
            return
        if make_primary:
            existing_primary = conn.execute(
                """
                SELECT workspace_id FROM project_workspace_links
                WHERE project_id = ? AND status = 'active' AND is_primary = 1
                """,
                (project_id,),
            ).fetchone()
            if (
                existing_primary is not None
                and str(existing_primary["workspace_id"]) != workspace_id
            ):
                self._issue(
                    conn,
                    run_id,
                    category="primary_workspace_conflict",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail="Legacy project has more than one possible Primary Workspace",
                )
                make_primary = False
        conn.execute(
            """
            INSERT INTO project_workspace_links
                (project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?, ?, ?)
            ON CONFLICT(project_id, workspace_id) DO UPDATE SET
                status = 'active', is_primary = excluded.is_primary,
                actor_id = excluded.actor_id, updated_at = excluded.updated_at
            """,
            (project_id, workspace_id, int(make_primary), owner_id, _now(), _now()),
        )

    def _import_tasks(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        user_aliases: Mapping[str, str],
    ) -> None:
        tasks = source.get("tasks", [])
        if not isinstance(tasks, list):
            return
        output_ranges = self._output_ranges(source)
        for index, item in enumerate(tasks):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            task_id = _as_record_id(item.get("task_id"), fallback=f"<missing-task-{index}>")
            source_path = "runtime/agentic_researcher.sqlite3#tasks"
            if self._has_result(conn, run_id, source_path, "task", task_id):
                continue
            target = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            project_id = self._optional_text(item.get("project_id"))
            workspace_id = self._optional_text(item.get("workspace_id"))
            environment_id = self._optional_text(item.get("environment_id"))
            raw_owner = item.get("owner_user_id")
            owner_id = user_aliases.get(str(raw_owner)) if raw_owner is not None else None
            invalid: list[str] = []
            owner_unmapped = owner_id is None
            if target is None:
                invalid.append("task target is missing")
            if owner_unmapped:
                invalid.append("task owner is not an auth user")
            project = (
                conn.execute(
                    "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
                ).fetchone()
                if project_id is not None
                else None
            )
            workspace = (
                conn.execute(
                    "SELECT environment_id FROM workspaces WHERE workspace_id = ?", (workspace_id,)
                ).fetchone()
                if workspace_id is not None
                else None
            )
            if project is None:
                invalid.append("task project is not imported")
            if workspace is None:
                invalid.append("task workspace is not imported")
            status = str(item.get("status", "unknown"))
            if environment_id is None:
                invalid.append("task Environment is missing")
            if (
                workspace is not None
                and environment_id is not None
                and str(workspace["environment_id"]) != environment_id
            ):
                invalid.append("task workspace/environment history conflicts")
            if invalid:
                detail = "; ".join(invalid)
                if owner_unmapped:
                    self._issue(
                        conn,
                        run_id,
                        category="task_owner_unmapped",
                        record_type="task",
                        record_id=task_id,
                        detail="Task owner cannot be mapped to a durable auth user",
                    )
                mapping_invalid = [
                    item for item in invalid if item != "task owner is not an auth user"
                ]
                if mapping_invalid:
                    self._issue(
                        conn,
                        run_id,
                        category="task_domain_mapping_invalid",
                        record_type="task",
                        record_id=task_id,
                        detail="; ".join(mapping_invalid),
                        blocking=(
                            target is None
                            or project is None
                            or workspace is None
                            or status in _ACTIVE_TASK_STATUSES
                        ),
                    )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="task",
                    source_record_id=task_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="task",
                    source_record_id=task_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            assert project_id is not None
            assert owner_id is not None
            version_id = self._ensure_legacy_context(conn, project_id, owner_id)
            snapshot_id = self._ensure_task_snapshot(conn, task_id, version_id)
            conn.execute(
                """
                UPDATE tasks
                SET owner_user_id = ?,
                    project_context_version_id = COALESCE(project_context_version_id, ?)
                WHERE task_id = ?
                """,
                (owner_id, version_id, task_id),
            )
            output_start, output_end = output_ranges.get(task_id, (None, None))
            if output_start is not None:
                conn.execute(
                    """
                    UPDATE agent_task_attempts
                    SET output_start_seq = COALESCE(output_start_seq, ?),
                        output_end_seq = COALESCE(output_end_seq, ?)
                    WHERE attempt_id = (
                        SELECT attempt_id FROM agent_task_attempts
                        WHERE task_id = ? ORDER BY attempt_seq DESC LIMIT 1
                    )
                    """,
                    (output_start, output_end, task_id),
                )
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="task",
                source_record_id=task_id,
                payload=item,
                status="imported",
                target_id=task_id,
                detail=f"pinned legacy Context snapshot {snapshot_id}",
            )

    @staticmethod
    def _output_ranges(source: Mapping[str, object]) -> dict[str, tuple[int | None, int | None]]:
        ranges: dict[str, tuple[int | None, int | None]] = {}
        rows = source.get("task_outputs", [])
        if not isinstance(rows, list):
            return ranges
        values: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            record = _as_record(row)
            if record is None:
                continue
            task_id = record.get("task_id")
            seq = record.get("seq")
            if isinstance(task_id, str) and isinstance(seq, int):
                values[task_id].append(seq)
        for task_id, sequences in values.items():
            ranges[task_id] = (min(sequences), max(sequences))
        return ranges

    def _ensure_task_snapshot(
        self, conn: sqlite3.Connection, task_id: str, context_version_id: str
    ) -> str:
        snapshot_id = f"legacy-snapshot-{task_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO context_snapshots (
                context_snapshot_id, context_version_id, fingerprint, content,
                source_manifest_json, created_at
            ) VALUES (?, ?, ?, '', '[]', ?)
            """,
            (snapshot_id, context_version_id, hashlib.sha256(b"").hexdigest(), _now()),
        )
        return snapshot_id

    def _import_relationships(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        edges = source.get("edges", [])
        if not isinstance(edges, list):
            return
        for index, item in enumerate(edges):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            edge_id = _as_record_id(item.get("edge_id"), fallback=f"edge-{index}")
            if self._has_result(
                conn, run_id, "runtime/task_edges.json", "task_relationship", edge_id
            ):
                continue
            source_task_id = self._optional_text(item.get("source_task_id"))
            target_task_id = self._optional_text(item.get("target_task_id"))
            source_exists = (
                conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (source_task_id,)).fetchone()
                if source_task_id is not None
                else None
            )
            target_exists = (
                conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (target_task_id,)).fetchone()
                if target_task_id is not None
                else None
            )
            if source_exists is None or target_exists is None:
                detail = "Legacy task edge references an unmapped Task"
                self._issue(
                    conn,
                    run_id,
                    category="orphan_task_relationship",
                    record_type="task_relationship",
                    record_id=edge_id,
                    detail=detail,
                    blocking=False,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path="runtime/task_edges.json",
                    record_type="task_relationship",
                    source_record_id=edge_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path="runtime/task_edges.json",
                    record_type="task_relationship",
                    source_record_id=edge_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            assert source_task_id is not None and target_task_id is not None
            relationship_id = self._relationship_id(source_task_id, target_task_id, "depends_on")
            existing = conn.execute(
                "SELECT 1 FROM task_relationships WHERE relationship_id = ?", (relationship_id,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO task_relationships (
                        source_task_id, target_task_id, relationship_type, created_at,
                        relationship_id, metadata_json
                    ) VALUES (?, ?, 'depends_on', ?, ?, ?)
                    """,
                    (
                        source_task_id,
                        target_task_id,
                        _now(),
                        relationship_id,
                        _canonical_json({"edge_id": edge_id}),
                    ),
                )
                status = "imported"
            else:
                status = "skipped"
            self._record_outcome(
                conn,
                run_id,
                source_path="runtime/task_edges.json",
                record_type="task_relationship",
                source_record_id=edge_id,
                payload=item,
                status=status,
                target_id=relationship_id,
                detail="legacy edge mapped as depends_on",
            )

    @staticmethod
    def _relationship_id(source_task_id: str, target_task_id: str, relationship_type: str) -> str:
        return (
            f"{len(source_task_id)}:{source_task_id}"
            f"{len(target_task_id)}:{target_task_id}"
            f"{len(relationship_type)}:{relationship_type}"
        )

    def _import_session_attempts(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        attempts = source.get("session_attempts", [])
        if not isinstance(attempts, list):
            attempts = []
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for index, item in enumerate(attempts):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            record_id = _as_record_id(item.get("id"), fallback=f"<missing-attempt-{index}>")
            task_id = self._optional_text(item.get("task_id"))
            source_path = "runtime/sessions.sqlite3#task_attempts"
            if self._has_result(conn, run_id, source_path, "session_attempt", record_id):
                continue
            if (
                task_id is None
                or conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                is None
            ):
                detail = "Legacy Session Attempt has no mapped Task"
                self._issue(
                    conn,
                    run_id,
                    category="session_attempt_unmapped",
                    record_type="session_attempt",
                    record_id=record_id,
                    detail=detail,
                    blocking=False,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="session_attempt",
                    source_record_id=record_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="session_attempt",
                    source_record_id=record_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            grouped[task_id].append(item)
        for task_id, task_attempts in grouped.items():
            task_attempts.sort(
                key=lambda item: (
                    str(item.get("started_at") or item.get("created_at") or ""),
                    str(item.get("created_at") or ""),
                    str(item.get("id") or ""),
                )
            )
            for item in task_attempts:
                self._import_one_session_attempt(conn, run_id, task_id, item)
        self._synthesise_missing_task_attempts(conn, run_id, source, set(grouped))

    def _import_task_sessions(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        """Map a legacy Session only when its Attempts identify one Task.

        ``task_sessions`` is an aggregate table and has no task_id itself.
        Keeping an ambiguous aggregate as a legacy artifact is safer than
        inventing a Task relationship.
        """

        attempts_by_session: dict[str, set[str]] = defaultdict(set)
        attempts = source.get("session_attempts", [])
        if isinstance(attempts, list):
            for raw_attempt in attempts:
                attempt = _as_record(raw_attempt)
                if attempt is None:
                    continue
                session_id = attempt.get("session_id")
                task_id = attempt.get("task_id")
                if isinstance(session_id, str) and isinstance(task_id, str) and task_id:
                    attempts_by_session[session_id].add(task_id)
        sessions = source.get("task_sessions", [])
        if not isinstance(sessions, list):
            return
        source_path = "runtime/sessions.sqlite3#task_sessions"
        for index, raw_session in enumerate(sessions):
            session = _as_record(raw_session)
            if session is None:
                continue
            session_id = _as_record_id(session.get("id"), fallback=f"<missing-session-{index}>")
            if self._has_result(conn, run_id, source_path, "session", session_id):
                continue
            task_ids = attempts_by_session.get(session_id, set())
            if len(task_ids) == 1:
                task_id = next(iter(task_ids))
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="session",
                    source_record_id=session_id,
                    payload=session,
                    status="skipped",
                    target_id=task_id,
                    detail="legacy Session is represented by mapped Task Attempts",
                )
                continue
            detail = "Legacy Session has no unique Task mapping"
            self._issue(
                conn,
                run_id,
                category="session_unmapped",
                record_type="session",
                record_id=session_id,
                detail=detail,
                blocking=False,
            )
            self._archive(
                conn,
                run_id,
                source_path=source_path,
                record_type="session",
                source_record_id=session_id,
                payload=session,
                reason=detail,
            )
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="session",
                source_record_id=session_id,
                payload=session,
                status="attention_needed",
                detail=detail,
            )

    def _apply_task_output_ranges(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        """Attach legacy output sequence bounds to the current Task Attempt."""

        rows = source.get("task_outputs", [])
        if not isinstance(rows, list):
            return
        source_path = "runtime/agentic_researcher.sqlite3#task_outputs"
        for index, raw_output in enumerate(rows):
            output = _as_record(raw_output)
            if output is None:
                continue
            task_id = self._optional_text(output.get("task_id"))
            seq = output.get("seq")
            record_id = str(seq) if isinstance(seq, int) else f"<missing-output-{index}>"
            if task_id is not None:
                record_id = f"{task_id}:{record_id}"
            if self._has_result(conn, run_id, source_path, "task_output", record_id):
                continue
            attempt = (
                conn.execute(
                    """
                    SELECT attempt_id FROM agent_task_attempts
                    WHERE task_id = ? ORDER BY attempt_seq DESC LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                if task_id is not None
                else None
            )
            if attempt is None or not isinstance(seq, int):
                detail = "Legacy task output has no mapped Task Attempt"
                self._issue(
                    conn,
                    run_id,
                    category="task_output_unmapped",
                    record_type="task_output",
                    record_id=record_id,
                    detail=detail,
                    blocking=False,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="task_output",
                    source_record_id=record_id,
                    payload=output,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="task_output",
                    source_record_id=record_id,
                    payload=output,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            conn.execute(
                """
                UPDATE agent_task_attempts
                SET output_start_seq = CASE
                        WHEN output_start_seq IS NULL OR output_start_seq > ? THEN ?
                        ELSE output_start_seq
                    END,
                    output_end_seq = CASE
                        WHEN output_end_seq IS NULL OR output_end_seq < ? THEN ?
                        ELSE output_end_seq
                    END
                WHERE attempt_id = ?
                """,
                (seq, seq, seq, seq, str(attempt["attempt_id"])),
            )
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="task_output",
                source_record_id=record_id,
                payload=output,
                status="imported",
                target_id=str(attempt["attempt_id"]),
                detail="output sequence range attached to latest imported Attempt",
            )

    def _import_one_session_attempt(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        task_id: str,
        item: Mapping[str, object],
    ) -> None:
        source_path = "runtime/sessions.sqlite3#task_attempts"
        record_id = _as_record_id(item.get("id"), fallback=f"legacy-{_sha256(item)[:12]}")
        if self._has_result(conn, run_id, source_path, "session_attempt", record_id):
            return
        attempt_id = f"legacy-session-attempt-{record_id}"
        existing = conn.execute(
            "SELECT attempt_id FROM agent_task_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if existing is None:
            next_seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(attempt_seq), 0) + 1 FROM agent_task_attempts WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            snapshot = self._task_snapshot_for(conn, task_id)
            raw_status = str(item.get("status", "completed"))
            status = self._attempt_status(raw_status)
            conn.execute(
                """
                INSERT INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id,
                    started_at, finished_at, token_usage_json, cost_usd,
                    data_refs_json, created_at
                ) VALUES (?, ?, ?, 'legacy_session', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    task_id,
                    next_seq,
                    status,
                    snapshot,
                    self._optional_text(item.get("started_at")),
                    self._optional_text(item.get("finished_at")),
                    self._json_text(item.get("token_usage_json")),
                    self._legacy_cost(item),
                    _canonical_json(
                        {
                            "legacy_session_id": item.get("session_id"),
                            "legacy_parent_attempt_id": item.get("parent_attempt_id"),
                            "legacy_attempt_id": record_id,
                        }
                    ),
                    self._source_time(item.get("created_at")),
                ),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id = ? WHERE task_id = ?", (attempt_id, task_id)
            )
            status_result = "imported"
        else:
            status_result = "skipped"
        self._record_outcome(
            conn,
            run_id,
            source_path=source_path,
            record_type="session_attempt",
            source_record_id=record_id,
            payload=item,
            status=status_result,
            target_id=attempt_id,
            detail="mapped by stable task/time order",
        )

    def _synthesise_missing_task_attempts(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        source: Mapping[str, object],
        source_attempt_tasks: set[str],
    ) -> None:
        tasks = source.get("tasks", [])
        if not isinstance(tasks, list):
            return
        for item in tasks:
            record = _as_record(item)
            if record is None:
                continue
            item = record
            task_id = self._optional_text(item.get("task_id"))
            if task_id is None or task_id in source_attempt_tasks:
                continue
            if conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                continue
            existing = conn.execute(
                "SELECT 1 FROM agent_task_attempts WHERE task_id = ?", (task_id,)
            ).fetchone()
            if existing is not None:
                continue
            snapshot = self._task_snapshot_for(conn, task_id)
            if snapshot is None:
                continue
            raw_status = str(item.get("status", "completed"))
            status = self._attempt_status(raw_status)
            attempt_id = f"legacy-task-attempt-{task_id}"
            now = _now()
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_task_attempts (
                    attempt_id, task_id, attempt_seq, trigger, status, context_snapshot_id,
                    started_at, finished_at, token_usage_json, created_at
                ) VALUES (?, ?, 1, 'legacy_task', ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    task_id,
                    status,
                    snapshot,
                    self._optional_text(item.get("started_at")),
                    self._optional_text(item.get("completed_at")),
                    self._json_text(item.get("token_usage_json")),
                    now,
                ),
            )
            conn.execute(
                "UPDATE tasks SET latest_attempt_id = ? WHERE task_id = ?", (attempt_id, task_id)
            )
        conn.commit()

    @staticmethod
    def _attempt_status(raw_status: str) -> str:
        mapping = {
            "pending": "queued",
            "active": "running",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "stopped": "stopped",
        }
        return mapping.get(raw_status, raw_status)

    @staticmethod
    def _legacy_cost(item: Mapping[str, object]) -> float | None:
        value = item.get("total_cost_usd")
        if isinstance(value, int | float):
            return float(value)
        return None

    def _task_snapshot_for(self, conn: sqlite3.Connection, task_id: str) -> str | None:
        row = conn.execute(
            "SELECT context_snapshot_id FROM context_snapshots WHERE context_snapshot_id = ?",
            (f"legacy-snapshot-{task_id}",),
        ).fetchone()
        return str(row["context_snapshot_id"]) if row is not None else None

    def _import_json_sessions(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        sessions = source.get("json_sessions", [])
        if not isinstance(sessions, list):
            return
        for index, item in enumerate(sessions):
            record = _as_record(item)
            if record is None:
                continue
            item = record
            session_id = _as_record_id(
                item.get("session_id"), fallback=f"<missing-session-{index}>"
            )
            source_path = "runtime/sessions.json"
            if self._has_result(conn, run_id, source_path, "session", session_id):
                continue
            task_id = self._optional_text(item.get("task_id"))
            task = (
                conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                if task_id is not None
                else None
            )
            if task is None:
                detail = "Legacy JSON Session has no mapped Task"
                self._issue(
                    conn,
                    run_id,
                    category="session_unmapped",
                    record_type="session",
                    record_id=session_id,
                    detail=detail,
                    blocking=False,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="session",
                    source_record_id=session_id,
                    payload=item,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="session",
                    source_record_id=session_id,
                    payload=item,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="session",
                source_record_id=session_id,
                payload=item,
                status="skipped",
                target_id=task_id,
                detail="JSON session is represented by imported Task Attempts",
            )

    def _import_runtime_checkpoints(
        self, conn: sqlite3.Connection, run_id: str, source: Mapping[str, object]
    ) -> None:
        checkpoints = source.get("checkpoints", [])
        if not isinstance(checkpoints, list):
            return
        for entry in checkpoints:
            if not isinstance(entry, tuple) or len(entry) != 2:
                continue
            source_path, payload = entry
            checkpoint = _as_record(payload)
            if not isinstance(source_path, str) or checkpoint is None:
                continue
            payload = checkpoint
            record_id = source_path
            if self._has_result(conn, run_id, source_path, "runtime_checkpoint", record_id):
                continue
            task_id = self._optional_text(payload.get("task_id")) or self._checkpoint_task_id(
                source_path
            )
            attempt = (
                conn.execute(
                    "SELECT attempt_id, status FROM agent_task_attempts WHERE task_id = ? ORDER BY attempt_seq DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
                if task_id is not None
                else None
            )
            if attempt is None:
                detail = "Runtime checkpoint has no mapped Task Attempt"
                self._issue(
                    conn,
                    run_id,
                    category="runtime_checkpoint_unmapped",
                    record_type="runtime_checkpoint",
                    record_id=record_id,
                    detail=detail,
                    blocking=False,
                )
                self._archive(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="runtime_checkpoint",
                    source_record_id=record_id,
                    payload=payload,
                    reason=detail,
                )
                self._record_outcome(
                    conn,
                    run_id,
                    source_path=source_path,
                    record_type="runtime_checkpoint",
                    source_record_id=record_id,
                    payload=payload,
                    status="attention_needed",
                    detail=detail,
                )
                continue
            runtime_id = f"legacy-runtime-{_sha256(record_id)[:24]}"
            existing = conn.execute(
                "SELECT 1 FROM agent_runtime_sessions WHERE runtime_session_id = ?", (runtime_id,)
            ).fetchone()
            if existing is None:
                attempt_status = str(attempt["status"])
                runtime_status = (
                    "finished" if attempt_status in _TERMINAL_ATTEMPT_STATUSES else "running"
                )
                conn.execute(
                    """
                    INSERT INTO agent_runtime_sessions (
                        runtime_session_id, attempt_id, launch_key, status, engine_name,
                        engine_session_key, runtime_metadata_json, created_at, started_at,
                        finished_at, adopted_at
                    ) VALUES (?, ?, ?, ?, 'legacy', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        runtime_id,
                        str(attempt["attempt_id"]),
                        f"legacy:{_sha256(record_id)}",
                        runtime_status,
                        self._optional_text(payload.get("session_id")),
                        _canonical_json(
                            {
                                "checkpoint_version": payload.get("version"),
                                "cwd": payload.get("cwd"),
                                "source_sha256": _sha256(payload),
                            }
                        ),
                        self._source_time(payload.get("created_at")),
                        self._source_time(payload.get("created_at")),
                        self._source_time(payload.get("created_at"))
                        if runtime_status == "finished"
                        else None,
                        _now(),
                    ),
                )
                result_status = "imported"
            else:
                result_status = "skipped"
            self._record_outcome(
                conn,
                run_id,
                source_path=source_path,
                record_type="runtime_checkpoint",
                source_record_id=record_id,
                payload=payload,
                status=result_status,
                target_id=runtime_id,
                detail="checkpoint mapped to latest Task Attempt",
            )

    @staticmethod
    def _checkpoint_task_id(source_path: str) -> str | None:
        parts = Path(source_path).parts
        if len(parts) >= 3 and parts[0] == "session-states":
            return parts[1]
        return None

    def _enter_phase(self, conn: sqlite3.Connection, run_id: str, phase: str) -> None:
        self._current_phase = phase
        self._update_checkpoint(conn, run_id, phase)
        conn.commit()

    def _complete_phase(self, conn: sqlite3.Connection, run_id: str, phase: str) -> None:
        self._current_phase = phase
        self._update_checkpoint(conn, run_id, f"{phase}:complete")
        conn.commit()

    def _update_checkpoint(self, conn: sqlite3.Connection, run_id: str, phase: str) -> None:
        completed = int(
            conn.execute(
                "SELECT COUNT(*) FROM domain_migration_record_results WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
        )
        now = _now()
        conn.execute(
            """
            UPDATE domain_migration_runs
            SET phase = ?, checkpoint_json = ?, heartbeat_at = ?, resume_metadata_json = ?
            WHERE run_id = ?
            """,
            (
                phase,
                _canonical_json(
                    {"phase": phase, "records_completed": completed, "updated_at": now}
                ),
                now,
                _canonical_json({"resumable": True, "last_phase": phase}),
                run_id,
            ),
        )

    def _set_run_status(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        status: str,
        phase: str,
        error: str | None = None,
    ) -> None:
        now = _now()
        metadata: dict[str, object] = {"resumable": status == "interrupted", "last_phase": phase}
        if error is not None:
            metadata["last_error"] = error
        conn.execute(
            """
            UPDATE domain_migration_runs
            SET status = ?, phase = ?, heartbeat_at = ?, finished_at = ?,
                checkpoint_json = ?, resume_metadata_json = ?, cutover_allowed = 0
            WHERE run_id = ?
            """,
            (
                status,
                phase,
                now,
                now if status in {"completed", "stale"} else None,
                _canonical_json({"phase": phase, "updated_at": now}),
                _canonical_json(metadata),
                run_id,
            ),
        )

    def _record_outcome(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        source_path: str,
        record_type: str,
        source_record_id: str,
        payload: object,
        status: str,
        target_id: str | None = None,
        detail: str = "",
    ) -> None:
        now = _now()
        conn.execute(
            """
            INSERT INTO domain_migration_record_results (
                record_result_id, run_id, source_path, record_type, source_record_id,
                source_payload_sha256, status, target_id, detail, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                run_id,
                source_path,
                record_type,
                source_record_id,
                _sha256(payload),
                status,
                target_id,
                detail,
                now,
                now,
            ),
        )
        self._update_checkpoint(conn, run_id, self._current_phase)
        conn.commit()
        self._processed_records += 1
        if (
            self._interrupt_after_records is not None
            and self._processed_records >= self._interrupt_after_records
        ):
            self._set_run_status(
                conn,
                run_id,
                status="interrupted",
                phase=self._current_phase,
                error="deterministic interruption after committed source outcome",
            )
            conn.commit()
            raise MigrationInterruptedError(run_id)

    @staticmethod
    def _has_result(
        conn: sqlite3.Connection,
        run_id: str,
        source_path: str,
        record_type: str,
        source_record_id: str,
    ) -> bool:
        return (
            conn.execute(
                """
                SELECT 1 FROM domain_migration_record_results
                WHERE run_id = ? AND source_path = ? AND record_type = ? AND source_record_id = ?
                """,
                (run_id, source_path, record_type, source_record_id),
            ).fetchone()
            is not None
        )

    def _archive(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        source_path: str,
        record_type: str,
        source_record_id: str,
        payload: object,
        reason: str,
    ) -> None:
        existing = conn.execute(
            """
            SELECT 1 FROM legacy_domain_records
            WHERE run_id = ? AND source_path = ? AND record_type = ? AND source_record_id = ?
            """,
            (run_id, source_path, record_type, source_record_id),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """
            INSERT INTO legacy_domain_records (
                legacy_record_id, run_id, record_type, payload_json, created_at,
                source_path, source_record_id, source_payload_sha256, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                run_id,
                record_type,
                _canonical_json(payload),
                _now(),
                source_path,
                source_record_id,
                _sha256(payload),
                reason,
            ),
        )

    @staticmethod
    def _issue(
        conn: sqlite3.Connection,
        run_id: str,
        *,
        category: str,
        record_type: str,
        record_id: str,
        detail: str,
        blocking: bool = True,
    ) -> None:
        existing = conn.execute(
            """
            SELECT 1 FROM domain_migration_issues
            WHERE run_id = ? AND category = ? AND record_type = ? AND record_id = ?
            """,
            (run_id, category, record_type, record_id),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """
            INSERT INTO domain_migration_issues (
                issue_id, run_id, category, record_type, record_id, severity, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                run_id,
                category,
                record_type,
                record_id,
                "blocking" if blocking else "non_blocking",
                detail,
                _now(),
            ),
        )

    def _refresh_counts(self, conn: sqlite3.Connection, run_id: str) -> None:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM domain_migration_record_results WHERE run_id = ? GROUP BY status
            """,
            (run_id,),
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        seed_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM environments WHERE environment_id = 'env-localhost'"
            ).fetchone()[0]
        )
        conn.execute(
            """
            UPDATE domain_migration_runs
            SET imported_count = ?, skipped_count = ?, attention_needed_count = ?
            WHERE run_id = ?
            """,
            (
                counts.get("imported", 0) + seed_count,
                counts.get("skipped", 0),
                counts.get("attention_needed", 0),
                run_id,
            ),
        )

    def _report(self, conn: sqlite3.Connection, run_id: str) -> MigrationReport:
        row = conn.execute(
            "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown domain migration run: {run_id}")
        blocking = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM domain_migration_issues AS issue
                WHERE issue.run_id = ? AND issue.severity = 'blocking'
                  AND NOT (
                      issue.resolution_status = 'resolved'
                      AND EXISTS (
                          SELECT 1 FROM domain_migration_resolutions AS resolution
                          WHERE resolution.run_id = issue.run_id
                            AND resolution.issue_id = issue.issue_id
                            AND resolution.resolution_type = issue.resolution_type
                            AND resolution.applied_at IS NOT NULL
                      )
                  )
                """,
                (run_id,),
            ).fetchone()[0]
        )
        return MigrationReport(
            run_id=run_id,
            status=str(row["status"]),
            imported_count=int(row["imported_count"]),
            skipped_count=int(row["skipped_count"]),
            attention_needed_count=int(row["attention_needed_count"]),
            blocking_issue_count=blocking,
            cutover_allowed=bool(row["cutover_allowed"]),
            phase=str(row["phase"]),
            source_manifest_sha256=self._optional_text(row["source_manifest_sha256"]),
            artifact_sha=self._optional_text(row["artifact_sha"]),
        )

    def _reconciliation_blockers(
        self, conn: sqlite3.Connection, run_id: str, run: sqlite3.Row
    ) -> list[str]:
        blockers = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT issue.category FROM domain_migration_issues AS issue
                WHERE issue.run_id = ? AND issue.severity = 'blocking'
                  AND NOT (
                      issue.resolution_status = 'resolved'
                      AND EXISTS (
                          SELECT 1 FROM domain_migration_resolutions AS resolution
                          WHERE resolution.run_id = issue.run_id
                            AND resolution.issue_id = issue.issue_id
                            AND resolution.resolution_type = issue.resolution_type
                            AND resolution.applied_at IS NOT NULL
                      )
                  )
                """,
                (run_id,),
            )
        ]
        try:
            with SourceSnapshotSet(self._state_root) as sources:
                current_manifest = self._manifest_json(sources, self._load_source_data(sources))
            current_digest = hashlib.sha256(current_manifest.encode("utf-8")).hexdigest()
            if current_digest != str(run["source_manifest_sha256"] or ""):
                blockers.append("source_manifest_changed")
        except SourceStaleError:
            blockers.append("source_manifest_changed")
        if str(run["status"]) != "completed":
            blockers.append("migration_run_incomplete")
        default_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM projects WHERE is_default = 1 AND status = 'active'"
            ).fetchone()[0]
        )
        if default_count == 0:
            blockers.append("default_project_missing")
        duplicate_primary = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT project_id FROM project_workspace_links
                    WHERE status = 'active' AND is_primary = 1 GROUP BY project_id HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        if duplicate_primary:
            blockers.append("primary_workspace_conflict")
        if int(
            conn.execute(
                """
                SELECT COUNT(*) FROM projects AS project
                WHERE project.status = 'active'
                  AND EXISTS (
                      SELECT 1 FROM project_workspace_links AS link
                      WHERE link.project_id = project.project_id AND link.status = 'active'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM project_workspace_links AS link
                      WHERE link.project_id = project.project_id
                        AND link.status = 'active'
                        AND link.is_primary = 1
                  )
                """
            ).fetchone()[0]
        ):
            blockers.append("primary_workspace_missing")
        if int(
            conn.execute(
                """
                SELECT COUNT(*) FROM project_workspace_links
                WHERE is_primary = 1 AND status != 'active'
                """
            ).fetchone()[0]
        ):
            blockers.append("primary_link_inactive")
        if int(
            conn.execute(
                """
                SELECT COUNT(*) FROM tasks t
                LEFT JOIN projects p ON p.project_id = t.project_id
                LEFT JOIN workspaces w ON w.workspace_id = t.workspace_id
                WHERE p.project_id IS NULL OR w.workspace_id IS NULL
                """
            ).fetchone()[0]
        ):
            blockers.append("task_project_or_workspace_missing")
        if int(
            conn.execute(
                """
                SELECT COUNT(*) FROM tasks t JOIN workspaces w ON w.workspace_id = t.workspace_id
                LEFT JOIN environments e ON e.environment_id = w.environment_id
                WHERE t.status IN ('pending', 'queued', 'starting', 'running', 'pausing', 'cancelling')
                  AND (e.environment_id IS NULL OR e.status != 'active')
                """
            ).fetchone()[0]
        ):
            blockers.append("workspace_environment_invalid")
        if int(
            conn.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE status IN ('pending', 'queued', 'starting', 'running', 'pausing', 'cancelling')
                  AND (project_context_version_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM agent_task_attempts a WHERE a.task_id = tasks.task_id
                  ))
                """
            ).fetchone()[0]
        ):
            blockers.append("active_task_missing_context_or_attempt")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            blockers.append("sqlite_integrity_check_failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            blockers.append("sqlite_foreign_key_check_failed")
        state = conn.execute(
            "SELECT constraints_ready FROM domain_cutover_state WHERE singleton = 1"
        ).fetchone()
        if state is None or not bool(state["constraints_ready"]):
            blockers.append("constraints_not_ready")
        return sorted(set(blockers))

    @staticmethod
    def _reconciliation_counts(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
        def scalar(sql: str, params: tuple[object, ...] = ()) -> int:
            return int(conn.execute(sql, params).fetchone()[0])

        return {
            "projects": scalar("SELECT COUNT(*) FROM projects"),
            "default_projects": scalar(
                "SELECT COUNT(*) FROM projects WHERE is_default = 1 AND status = 'active'"
            ),
            "workspaces": scalar("SELECT COUNT(*) FROM workspaces"),
            "primary_links": scalar(
                "SELECT COUNT(*) FROM project_workspace_links WHERE status = 'active' AND is_primary = 1"
            ),
            "environments": scalar("SELECT COUNT(*) FROM environments"),
            "legacy_environment_placeholders": scalar(
                "SELECT COUNT(*) FROM environments WHERE status = 'disabled'"
            ),
            "project_members": scalar("SELECT COUNT(*) FROM project_members"),
            "tasks": scalar("SELECT COUNT(*) FROM tasks"),
            "attempts": scalar("SELECT COUNT(*) FROM agent_task_attempts"),
            "runtime_sessions": scalar("SELECT COUNT(*) FROM agent_runtime_sessions"),
            "task_relationships": scalar("SELECT COUNT(*) FROM task_relationships"),
            "legacy_records": scalar(
                "SELECT COUNT(*) FROM legacy_domain_records WHERE run_id = ?", (run_id,)
            ),
            "record_results": scalar(
                "SELECT COUNT(*) FROM domain_migration_record_results WHERE run_id = ?", (run_id,)
            ),
            "migration_issues": scalar(
                "SELECT COUNT(*) FROM domain_migration_issues WHERE run_id = ?", (run_id,)
            ),
        }

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _source_time(value: object) -> str:
        return value if isinstance(value, str) and value else _now()

    @staticmethod
    def _json_text(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return _canonical_json(value)

    @staticmethod
    def _json_object(value: object) -> dict[str, object]:
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        parsed_record = _as_record(parsed)
        return parsed_record if parsed_record is not None else {}
