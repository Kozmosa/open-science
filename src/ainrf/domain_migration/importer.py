"""Application-level legacy importer and reconciliation for the v2 schema."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain_migration.sources import capture_source_manifest


@dataclass(frozen=True, slots=True)
class MigrationReport:
    run_id: str
    status: str
    imported_count: int
    skipped_count: int
    attention_needed_count: int
    blocking_issue_count: int
    cutover_allowed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_items(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON source {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON source {path}: expected an object")
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
        raise ValueError(f"Invalid JSON source {path}: items must be a list of objects")
    return [dict(item) for item in raw_items]


class DomainImporter:
    """Idempotently shadow-import legacy sources into the additive v2 tables."""

    def __init__(self, state_root: Path) -> None:
        self._state_root = state_root
        self._runtime_root = state_root / "runtime"
        self._db_path = self._runtime_root / "agentic_researcher.sqlite3"
        self._auth_path = self._runtime_root / "auth.sqlite3"

    def run(self, *, mode: str = "validate") -> MigrationReport:
        if mode not in {"validate", "apply"}:
            raise ValueError("mode must be validate or apply")
        self._runtime_root.mkdir(parents=True, exist_ok=True)
        # Establish the additive target schema before taking a legacy-task
        # fingerprint. The first run must not differ merely because the target
        # database file did not exist yet.
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
        manifest = capture_source_manifest(self._state_root)
        manifest_json = json.dumps(manifest.as_dict(), sort_keys=True)
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
            existing = conn.execute(
                """
                SELECT run_id, source_manifest_json
                FROM domain_migration_runs
                WHERE mode = ? AND status = 'completed'
                ORDER BY started_at DESC LIMIT 1
                """,
                (mode,),
            ).fetchone()
            if existing is not None and self._same_source_content(
                manifest_json, str(existing["source_manifest_json"])
            ):
                return self._report(conn, str(existing["run_id"]))

            run_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO domain_migration_runs
                    (run_id, mode, source_manifest_json, code_version, status, started_at)
                VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (run_id, mode, manifest_json, "domain-v2-s0-b3", _now()),
            )
            users = self._legacy_users()
            counters = {"imported": 0, "skipped": 0, "attention": 0}
            self._ensure_seed_environment(conn, counters)
            project_ids = self._import_projects(conn, run_id, users, counters)
            self._import_workspaces(conn, run_id, users, project_ids, counters)
            self._import_tasks_and_attempts(conn, run_id, project_ids, counters)
            blocking = conn.execute(
                "SELECT COUNT(*) FROM domain_migration_issues WHERE run_id = ? AND severity = 'blocking'",
                (run_id,),
            ).fetchone()[0]
            conn.execute(
                """
                UPDATE domain_migration_runs
                SET status = 'completed', imported_count = ?, skipped_count = ?, attention_needed_count = ?,
                    cutover_allowed = 0, finished_at = ?
                WHERE run_id = ?
                """,
                (counters["imported"], counters["skipped"], counters["attention"], _now(), run_id),
            )
            conn.commit()
            _ = blocking
            return self._report(conn, run_id)

    @staticmethod
    def _same_source_content(current: str, previous: str) -> bool:
        """Compare immutable content identities, ignoring SQLite file metadata.

        SQLite WAL/checkpoint activity can change inode/mtime while a stable
        backup snapshot has exactly the same logical source contents.
        """

        def content_set(raw: str) -> set[tuple[str, str, int]]:
            payload = json.loads(raw)
            files = payload.get("files", [])
            return {
                (str(item["relative_path"]), str(item["sha256"]), int(item["size"]))
                for item in files
            }

        return content_set(current) == content_set(previous)

    def reconcile(self, run_id: str | None = None) -> MigrationReport:
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")
            if run_id is None:
                row = conn.execute(
                    "SELECT run_id FROM domain_migration_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    raise ValueError("No domain migration run exists")
                run_id = str(row["run_id"])
            return self._report(conn, run_id)

    def _legacy_users(self) -> dict[str, str]:
        if not self._auth_path.exists():
            return {}
        with closing(sqlite3.connect(f"file:{self._auth_path}?mode=ro", uri=True)) as conn:
            try:
                rows = conn.execute("SELECT id, username FROM users").fetchall()
            except sqlite3.Error:
                return {}
        return {
            str(value): str(identifier)
            for identifier, username in rows
            for value in (identifier, username)
        }

    def _issue(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        category: str,
        record_type: str,
        record_id: str,
        detail: str,
        blocking: bool = True,
    ) -> None:
        conn.execute(
            """
            INSERT INTO domain_migration_issues
                (issue_id, run_id, category, record_type, record_id, severity, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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

    def _ensure_seed_environment(self, conn: sqlite3.Connection, counters: dict[str, int]) -> None:
        row = conn.execute(
            "SELECT environment_id FROM environments WHERE environment_id = 'env-localhost'"
        ).fetchone()
        if row is not None:
            counters["skipped"] += 1
            return
        now = _now()
        conn.execute(
            """
            INSERT INTO environments
                (environment_id, alias, owner_user_id, display_name, connection_json, is_seed, status, created_at, updated_at)
            VALUES ('env-localhost', 'localhost', NULL, 'Localhost', '{}', 1, 'active', ?, ?)
            """,
            (now, now),
        )
        counters["imported"] += 1

    def _import_projects(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        users: dict[str, str],
        counters: dict[str, int],
    ) -> set[str]:
        result: set[str] = set()
        for item in _read_items(self._runtime_root / "projects.json"):
            project_id = str(item.get("project_id", ""))
            owner = item.get("owner_user_id")
            owner_id = users.get(str(owner)) if owner is not None else None
            if not project_id or owner_id is None:
                self._issue(
                    conn,
                    run_id,
                    category="owner_unmapped",
                    record_type="project",
                    record_id=project_id or "<missing>",
                    detail="Project owner cannot be mapped to an auth user",
                )
                counters["attention"] += 1
                continue
            now = _now()
            conn.execute(
                """
                INSERT OR IGNORE INTO projects
                    (project_id, owner_user_id, name, description, status, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    project_id,
                    owner_id,
                    str(item.get("name", project_id)),
                    item.get("description"),
                    int(project_id == "default"),
                    now,
                    now,
                ),
            )
            self._ensure_legacy_context(conn, project_id, owner_id)
            result.add(project_id)
            counters["imported"] += 1
        return result

    def _ensure_legacy_context(
        self, conn: sqlite3.Connection, project_id: str, owner_id: str
    ) -> None:
        version_id = f"legacy-empty-{project_id}"
        conn.execute(
            """
            INSERT OR IGNORE INTO project_context_versions
                (context_version_id, project_id, content, fingerprint, is_active, created_by_user_id, created_at)
            VALUES (?, ?, '', ?, 1, ?, ?)
            """,
            (version_id, project_id, version_id, owner_id, _now()),
        )

    def _import_workspaces(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        users: dict[str, str],
        project_ids: set[str],
        counters: dict[str, int],
    ) -> None:
        for item in _read_items(self._runtime_root / "workspaces.json"):
            workspace_id = str(item.get("workspace_id", ""))
            owner_id = users.get(str(item.get("owner_user_id")))
            path = item.get("default_workdir")
            project_id = str(item.get("project_id", ""))
            if (
                not workspace_id
                or owner_id is None
                or not isinstance(path, str)
                or not Path(path).is_absolute()
            ):
                self._issue(
                    conn,
                    run_id,
                    category="workspace_unmapped",
                    record_type="workspace",
                    record_id=workspace_id or "<missing>",
                    detail="Workspace owner or absolute path cannot be inferred",
                )
                counters["attention"] += 1
                continue
            canonical_path = str(Path(path).resolve())
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO workspaces
                       (workspace_id, owner_user_id, environment_id, canonical_path, label, description, legacy_project_id, created_at, updated_at)
                       VALUES (?, ?, 'env-localhost', ?, ?, ?, ?, ?, ?)""",
                    (
                        workspace_id,
                        owner_id,
                        canonical_path,
                        str(item.get("label", workspace_id)),
                        item.get("description"),
                        project_id or None,
                        _now(),
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError:
                self._issue(
                    conn,
                    run_id,
                    category="canonical_path_conflict",
                    record_type="workspace",
                    record_id=workspace_id,
                    detail="Workspace owner/environment/path conflicts with another legacy workspace",
                )
                counters["attention"] += 1
                continue
            if project_id in project_ids:
                conn.execute(
                    """INSERT OR IGNORE INTO project_workspace_links
                       (project_id, workspace_id, status, is_primary, actor_id, created_at, updated_at)
                       VALUES (?, ?, 'active', ?, ?, ?, ?)""",
                    (
                        project_id,
                        workspace_id,
                        int(item.get("workspace_id") == "workspace-default"),
                        owner_id,
                        _now(),
                        _now(),
                    ),
                )
            counters["imported"] += 1

    def _import_tasks_and_attempts(
        self, conn: sqlite3.Connection, run_id: str, project_ids: set[str], counters: dict[str, int]
    ) -> None:
        rows = conn.execute(
            "SELECT task_id, project_id, status, owner_user_id FROM tasks"
        ).fetchall()
        for row in rows:
            task_id, project_id, status, owner = (
                str(row[key]) for key in ("task_id", "project_id", "status", "owner_user_id")
            )
            if project_id not in project_ids:
                self._issue(
                    conn,
                    run_id,
                    category="task_project_missing",
                    record_type="task",
                    record_id=task_id,
                    detail="Task references a legacy project not imported",
                )
                counters["attention"] += 1
                continue
            version_id = f"legacy-empty-{project_id}"
            conn.execute(
                "UPDATE tasks SET project_context_version_id = ? WHERE task_id = ?",
                (version_id, task_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO agent_task_attempts
                   (attempt_id, task_id, attempt_seq, trigger, status, created_at)
                   VALUES (?, ?, 1, 'legacy', ?, ?)""",
                (f"legacy-attempt-{task_id}", task_id, status, _now()),
            )
            counters["imported"] += 1

    def _report(self, conn: sqlite3.Connection, run_id: str) -> MigrationReport:
        row = conn.execute(
            "SELECT * FROM domain_migration_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown domain migration run: {run_id}")
        blocking = conn.execute(
            "SELECT COUNT(*) FROM domain_migration_issues WHERE run_id = ? AND severity = 'blocking'",
            (run_id,),
        ).fetchone()[0]
        return MigrationReport(
            run_id=run_id,
            status=str(row["status"]),
            imported_count=int(row["imported_count"]),
            skipped_count=int(row["skipped_count"]),
            attention_needed_count=int(row["attention_needed_count"]),
            blocking_issue_count=int(blocking),
            cutover_allowed=bool(row["cutover_allowed"]),
        )
