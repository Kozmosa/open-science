"""Versioned, auditable Project Context assembly and Task pinning."""

from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from ainrf.db import connect, run_pending
from ainrf.domain.service import (
    DomainAuthorizationService,
    DomainConflictError,
    DomainNotFoundError,
    DomainPermissionError,
)
from ainrf.domain_control import MaintenanceModeError

DEFAULT_CONTEXT_BYTE_BUDGET = 32 * 1024
DEFAULT_PREVIEW_TTL_SECONDS = 30 * 60
PLATFORM_CONSTRAINTS_VERSION = "openscience-platform-v1"
DEFAULT_PLATFORM_CONSTRAINTS = (
    "Operate within the selected OpenScience Project and Workspace. "
    "Respect tenant isolation, do not expose credentials or private paths, "
    "and report uncertainty instead of assuming unavailable state."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): item for key, item in decoded.items()}


def _load_json_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [
        {str(key): item for key, item in entry.items()}
        for entry in decoded
        if isinstance(entry, dict)
    ]


def _utf8_prefix(value: str, byte_budget: int) -> str:
    if byte_budget <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_budget:
        return value
    return encoded[:byte_budget].decode("utf-8", errors="ignore")


@dataclass(frozen=True, slots=True)
class ContextSource:
    """One ordered, fingerprinted input to a Context Snapshot."""

    source_type: str
    source_id: str
    source_version: str
    label: str
    content: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.content)


@dataclass(frozen=True, slots=True)
class ContextAssembly:
    """The deterministic result produced by :class:`ContextAssembler`."""

    content: str
    fingerprint: str
    source_manifest: tuple[dict[str, object], ...]
    byte_budget: int
    truncated: bool

    @property
    def source_manifest_json(self) -> str:
        return _canonical_json(list(self.source_manifest))


class ContextAssembler:
    """Build a bounded Context Snapshot in the one allowed source order."""

    def __init__(
        self,
        *,
        byte_budget: int = DEFAULT_CONTEXT_BYTE_BUDGET,
        platform_constraints: str = DEFAULT_PLATFORM_CONSTRAINTS,
    ) -> None:
        if byte_budget < 0:
            raise ValueError("Context byte budget cannot be negative")
        self.byte_budget = byte_budget
        self.platform_constraints = platform_constraints

    def platform_source(self) -> ContextSource:
        return ContextSource(
            source_type="platform_constraints",
            source_id=PLATFORM_CONSTRAINTS_VERSION,
            source_version=PLATFORM_CONSTRAINTS_VERSION,
            label="Platform Constraints",
            content=self.platform_constraints,
        )

    def assemble(self, sources: Sequence[ContextSource]) -> ContextAssembly:
        required_order = (
            "platform_constraints",
            "project_brief",
            "workspace_context",
            "task_request",
        )
        actual_order = tuple(source.source_type for source in sources)
        if actual_order != required_order:
            raise ValueError("Context sources must use the required fixed order")

        remaining = self.byte_budget
        chunks: list[str] = []
        manifest: list[dict[str, object]] = []
        truncated = False
        for position, source in enumerate(sources):
            rendered = f"## {source.label}\n{source.content}\n\n"
            rendered_bytes = len(rendered.encode("utf-8"))
            included = _utf8_prefix(rendered, remaining)
            included_bytes = len(included.encode("utf-8"))
            source_truncated = included_bytes != rendered_bytes
            truncated = truncated or source_truncated
            chunks.append(included)
            remaining -= included_bytes
            manifest.append(
                {
                    "position": position,
                    "source_type": source.source_type,
                    "source_id": source.source_id,
                    "source_version": source.source_version,
                    "fingerprint": source.fingerprint,
                    "input_bytes": len(source.content.encode("utf-8")),
                    "rendered_bytes": rendered_bytes,
                    "included_bytes": included_bytes,
                    "truncated": source_truncated,
                }
            )

        content = "".join(chunks)
        fingerprint = _fingerprint(
            _canonical_json(
                {
                    "assembler_version": 1,
                    "byte_budget": self.byte_budget,
                    "truncated": truncated,
                    "source_manifest": manifest,
                    "content": content,
                }
            )
        )
        return ContextAssembly(
            content=content,
            fingerprint=fingerprint,
            source_manifest=tuple(manifest),
            byte_budget=self.byte_budget,
            truncated=truncated,
        )


class ProjectContextService:
    """Own the Project Context lifecycle and explicit Task Context changes."""

    def __init__(
        self,
        state_root: Path,
        *,
        context_byte_budget: int = DEFAULT_CONTEXT_BYTE_BUDGET,
        platform_constraints: str = DEFAULT_PLATFORM_CONSTRAINTS,
    ) -> None:
        self._state_root = state_root
        self._db_path = state_root / "runtime" / "agentic_researcher.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._assembler = ContextAssembler(
            byte_budget=context_byte_budget,
            platform_constraints=platform_constraints,
        )
        with closing(connect(self._db_path)) as conn:
            run_pending(conn, "agentic_researcher")

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    @staticmethod
    def _begin_domain_write(conn: sqlite3.Connection) -> None:
        """Serialize a Context mutation with the persistent maintenance barrier.

        Context has public writers that are also called independently of
        :class:`TaskApplicationService`.  Acquiring the SQLite writer before
        reading the epoch ensures a maintenance transition cannot race a
        snapshot, preview, or draft mutation through a separate connection.
        """

        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT is_active FROM domain_maintenance_state WHERE singleton = 1"
        ).fetchone()
        if state is None or bool(state["is_active"]):
            raise MaintenanceModeError("domain writes are paused for maintenance")

    @staticmethod
    def _user_id(user: Mapping[str, object]) -> str:
        value = user.get("id")
        if not isinstance(value, str) or not value:
            raise DomainPermissionError("Authenticated user ID is required")
        return value

    def save_draft(
        self, project_id: str, content: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            now = _now()
            conn.execute(
                """INSERT INTO project_context_drafts(project_id, content, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET content = excluded.content,
                       updated_by_user_id = excluded.updated_by_user_id, updated_at = excluded.updated_at""",
                (project_id, content, self._user_id(user), now),
            )
            self._audit(
                conn, self._user_id(user), "project_context.draft_saved", "project", project_id
            )
            conn.commit()
            return {
                "project_id": project_id,
                "content": content,
                "fingerprint": _fingerprint(content),
                "updated_by_user_id": self._user_id(user),
                "updated_at": now,
            }

    def get_context(self, project_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            auth = DomainAuthorizationService(conn)
            role = auth.require_project_viewer(project_id, dict(user))
            active = conn.execute(
                """SELECT context_version_id, project_id, content, fingerprint, is_active,
                          created_by_user_id, created_at
                   FROM project_context_versions
                   WHERE project_id = ? AND is_active = 1""",
                (project_id,),
            ).fetchone()
            draft = None
            if role in {"admin", "owner", "editor"}:
                draft_row = conn.execute(
                    """SELECT content, updated_by_user_id, updated_at
                       FROM project_context_drafts WHERE project_id = ?""",
                    (project_id,),
                ).fetchone()
                if draft_row is not None:
                    draft_content = str(draft_row["content"])
                    draft = {
                        "content": draft_content,
                        "fingerprint": _fingerprint(draft_content),
                        "updated_by_user_id": str(draft_row["updated_by_user_id"]),
                        "updated_at": str(draft_row["updated_at"]),
                    }
            return {
                "project_id": project_id,
                "active_version": self._version_payload(active) if active is not None else None,
                "draft": draft,
            }

    def publish(
        self,
        project_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_publisher(project_id, dict(user))
            draft = conn.execute(
                "SELECT content FROM project_context_drafts WHERE project_id = ?", (project_id,)
            ).fetchone()
            if draft is None:
                raise DomainNotFoundError("project context draft")
            content = str(draft["content"])
            actor_user_id = self._user_id(user)
            request = {
                "project_id": project_id,
                "draft_fingerprint": _fingerprint(content),
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn, actor_user_id, "project.context.publish", idempotency_key, request
                )
                if cached is not None:
                    return cached
            version_id = f"context-{uuid4().hex}"
            now = _now()
            conn.execute(
                "UPDATE project_context_versions SET is_active = 0 WHERE project_id = ?",
                (project_id,),
            )
            conn.execute(
                """INSERT INTO project_context_versions
                   (context_version_id, project_id, content, fingerprint, is_active, created_by_user_id, created_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (version_id, project_id, content, _fingerprint(content), actor_user_id, now),
            )
            result: dict[str, object] = {
                "context_version_id": version_id,
                "project_id": project_id,
                "fingerprint": _fingerprint(content),
                "content": content,
                "is_active": True,
                "created_by_user_id": actor_user_id,
                "created_at": now,
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.publish",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project_context.published", "project", project_id)
            conn.commit()
            return result

    def list_versions(self, project_id: str, user: Mapping[str, object]) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            rows = conn.execute(
                """SELECT context_version_id, project_id, content, fingerprint, is_active,
                          created_by_user_id, created_at
                   FROM project_context_versions WHERE project_id = ?
                   ORDER BY created_at DESC, context_version_id DESC""",
                (project_id,),
            ).fetchall()
            return [self._version_payload(row) for row in rows]

    def get_version(
        self, project_id: str, context_version_id: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            version = self._version(conn, project_id, context_version_id)
            return self._version_payload(version)

    def diff_versions(
        self,
        project_id: str,
        before_version_id: str,
        after_version_id: str,
        user: Mapping[str, object],
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            before = self._version(conn, project_id, before_version_id)
            after = self._version(conn, project_id, after_version_id)
            return {
                "project_id": project_id,
                "before_context_version_id": before_version_id,
                "after_context_version_id": after_version_id,
                "diff": self._unified_diff(str(before["content"]), str(after["content"])),
            }

    def create_candidate(
        self,
        project_id: str,
        content: str,
        user: Mapping[str, object],
        *,
        source_metadata: Mapping[str, object] | None = None,
        source_task_id: str | None = None,
        source_attempt_id: str | None = None,
        source_message_start_seq: int | None = None,
        source_message_end_seq: int | None = None,
        source_output_start_seq: int | None = None,
        source_output_end_seq: int | None = None,
    ) -> dict[str, object]:
        self._validate_ranges(
            source_message_start_seq,
            source_message_end_seq,
            source_output_start_seq,
            source_output_end_seq,
        )
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            auth = DomainAuthorizationService(conn)
            auth.require_project_editor(project_id, dict(user))
            self._validate_candidate_provenance(
                conn,
                project_id=project_id,
                source_task_id=source_task_id,
                source_attempt_id=source_attempt_id,
            )
            candidate_id = f"candidate-{uuid4().hex}"
            now = _now()
            conn.execute(
                """INSERT INTO project_context_candidates (
                       candidate_id, project_id, content, status, created_at,
                       created_by_user_id, source_metadata_json, source_task_id,
                       source_attempt_id, source_message_start_seq, source_message_end_seq,
                       source_output_start_seq, source_output_end_seq
                   ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    project_id,
                    content,
                    now,
                    self._user_id(user),
                    _canonical_json(dict(source_metadata or {})),
                    source_task_id,
                    source_attempt_id,
                    source_message_start_seq,
                    source_message_end_seq,
                    source_output_start_seq,
                    source_output_end_seq,
                ),
            )
            self._audit(
                conn,
                self._user_id(user),
                "project_context.candidate_created",
                "candidate",
                candidate_id,
            )
            conn.commit()
            return self._candidate_payload(
                conn.execute(
                    "SELECT * FROM project_context_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
            )

    def list_candidates(
        self, project_id: str, user: Mapping[str, object]
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            rows = conn.execute(
                """SELECT * FROM project_context_candidates WHERE project_id = ?
                   ORDER BY created_at DESC, candidate_id DESC""",
                (project_id,),
            ).fetchall()
            return [self._candidate_payload(row) for row in rows]

    def accept_candidate(
        self, project_id: str, candidate_id: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            candidate = self._candidate(conn, project_id, candidate_id)
            if candidate["status"] == "rejected":
                raise DomainConflictError("A rejected Context Candidate cannot be accepted")
            draft = conn.execute(
                "SELECT content FROM project_context_drafts WHERE project_id = ?", (project_id,)
            ).fetchone()
            current = str(draft["content"]) if draft is not None else ""
            if candidate["status"] == "accepted":
                return {
                    "candidate": self._candidate_payload(candidate),
                    "draft": self._draft_payload(conn, project_id),
                }
            proposed = self._append_candidate(current, str(candidate["content"]))
            now = _now()
            conn.execute(
                """INSERT INTO project_context_drafts(project_id, content, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET content = excluded.content,
                       updated_by_user_id = excluded.updated_by_user_id, updated_at = excluded.updated_at""",
                (project_id, proposed, self._user_id(user), now),
            )
            conn.execute(
                """UPDATE project_context_candidates
                   SET status = 'accepted', accepted_by_user_id = ?, accepted_at = ?
                   WHERE candidate_id = ?""",
                (self._user_id(user), now, candidate_id),
            )
            self._audit(
                conn,
                self._user_id(user),
                "project_context.candidate_accepted",
                "candidate",
                candidate_id,
            )
            conn.commit()
            updated = self._candidate(conn, project_id, candidate_id)
            return {
                "candidate": self._candidate_payload(updated),
                "draft": self._draft_payload(conn, project_id),
            }

    def reject_candidate(
        self,
        project_id: str,
        candidate_id: str,
        user: Mapping[str, object],
        *,
        reason: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            candidate = self._candidate(conn, project_id, candidate_id)
            if candidate["status"] == "accepted":
                raise DomainConflictError("An accepted Context Candidate cannot be rejected")
            if candidate["status"] == "rejected":
                return self._candidate_payload(candidate)
            now = _now()
            conn.execute(
                """UPDATE project_context_candidates
                   SET status = 'rejected', rejected_by_user_id = ?, rejected_at = ?,
                       rejection_reason = ? WHERE candidate_id = ?""",
                (self._user_id(user), now, reason, candidate_id),
            )
            self._audit(
                conn,
                self._user_id(user),
                "project_context.candidate_rejected",
                "candidate",
                candidate_id,
            )
            conn.commit()
            return self._candidate_payload(self._candidate(conn, project_id, candidate_id))

    def create_fragment(
        self,
        project_id: str,
        content: str,
        user: Mapping[str, object],
        *,
        source_type: str,
        source_metadata: Mapping[str, object] | None = None,
        source_version: str | None = None,
        sort_order: int = 0,
        byte_budget: int | None = None,
    ) -> dict[str, object]:
        if not source_type:
            raise DomainConflictError("Context Fragment source_type is required")
        if byte_budget is not None and byte_budget < 0:
            raise DomainConflictError("Context Fragment byte_budget cannot be negative")
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            fragment_id = f"fragment-{uuid4().hex}"
            now = _now()
            conn.execute(
                """INSERT INTO project_context_fragments (
                       fragment_id, project_id, source_type, content, created_at, source_version,
                       source_fingerprint, sort_order, byte_budget, created_by_user_id,
                       source_metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fragment_id,
                    project_id,
                    source_type,
                    content,
                    now,
                    source_version,
                    _fingerprint(content),
                    sort_order,
                    byte_budget,
                    self._user_id(user),
                    _canonical_json(dict(source_metadata or {})),
                ),
            )
            self._audit(
                conn,
                self._user_id(user),
                "project_context.fragment_created",
                "fragment",
                fragment_id,
            )
            conn.commit()
            return self._fragment_payload(
                conn.execute(
                    "SELECT * FROM project_context_fragments WHERE fragment_id = ?", (fragment_id,)
                ).fetchone()
            )

    def list_fragments(
        self, project_id: str, user: Mapping[str, object]
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_project_viewer(project_id, dict(user))
            rows = conn.execute(
                """SELECT * FROM project_context_fragments WHERE project_id = ?
                   ORDER BY sort_order, created_at, fragment_id""",
                (project_id,),
            ).fetchall()
            return [self._fragment_payload(row) for row in rows]

    def pin_active_context(self, task_id: str, project_id: str) -> str:
        """Internal compatibility helper: pin a fresh active Context Snapshot."""

        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            task = self._task_for_project(conn, task_id, project_id)
            snapshot_id, version_id = self._create_active_snapshot_for_task_in_transaction(
                conn,
                project_id=project_id,
                workspace_id=str(task["workspace_id"]),
                task_id=task_id,
                task_prompt=str(task["prompt"]),
            )
            conn.execute(
                """UPDATE tasks
                   SET project_context_version_id = ?, project_context_snapshot_id = ?, updated_at = ?
                   WHERE task_id = ?""",
                (version_id, snapshot_id, _now(), task_id),
            )
            conn.commit()
            return snapshot_id

    def create_active_snapshot_for_task_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        task_id: str,
        task_prompt: str,
    ) -> tuple[str, str]:
        """Create an unpinned Snapshot for a new Task inside its write transaction."""

        return self._create_active_snapshot_for_task_in_transaction(
            conn,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
            task_prompt=task_prompt,
        )

    def create_snapshot_for_task_context_version_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        task_id: str,
        task_prompt: str,
        context_version_id: str,
    ) -> str:
        """Freeze an explicitly selected Project Context Version for a Task.

        A Task move deliberately cannot silently adopt the target Project's
        active Context Version.  The caller supplies the reviewed immutable
        Version and this helper assembles and inserts the corresponding
        Snapshot in the caller's existing lifecycle transaction.
        """

        assembly = self._assemble_for_task(
            conn,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
            task_prompt=task_prompt,
            context_version_id=context_version_id,
        )
        return self._insert_snapshot(conn, context_version_id, assembly)

    def ensure_task_snapshot(self, task_id: str) -> str:
        """Backfill an old unstarted Task's explicit Snapshot without drift."""

        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            snapshot_id = self.ensure_task_snapshot_in_transaction(conn, task_id)
            conn.commit()
            return snapshot_id

    def ensure_task_snapshot_in_transaction(self, conn: sqlite3.Connection, task_id: str) -> str:
        """Backfill a Task pin using an already-open task/Attempt transaction."""

        task = conn.execute(
            """SELECT task_id, project_id, workspace_id, prompt, project_context_version_id,
                      project_context_snapshot_id
               FROM tasks WHERE task_id = ?""",
            (task_id,),
        ).fetchone()
        if task is None:
            raise DomainNotFoundError(task_id)
        existing = task["project_context_snapshot_id"]
        if isinstance(existing, str) and existing:
            return existing
        version_id = task["project_context_version_id"]
        if isinstance(version_id, str) and version_id:
            assembly = self._assemble_for_task(
                conn,
                project_id=str(task["project_id"]),
                workspace_id=str(task["workspace_id"]),
                task_id=task_id,
                task_prompt=str(task["prompt"]),
                context_version_id=version_id,
            )
        else:
            assembly = self._assemble_for_task(
                conn,
                project_id=str(task["project_id"]),
                workspace_id=str(task["workspace_id"]),
                task_id=task_id,
                task_prompt=str(task["prompt"]),
            )
            version_id = self._active_version(conn, str(task["project_id"]))["context_version_id"]
        snapshot_id = self._insert_snapshot(conn, str(version_id), assembly)
        conn.execute(
            """UPDATE tasks
               SET project_context_version_id = ?, project_context_snapshot_id = ?, updated_at = ?
               WHERE task_id = ?""",
            (version_id, snapshot_id, _now(), task_id),
        )
        return snapshot_id

    def preview_task_context_update(
        self, task_id: str, project_id: str, user: Mapping[str, object]
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            task = self._authorize_task_context_update(conn, task_id, project_id, user)
            assembly = self._assemble_for_task(
                conn,
                project_id=project_id,
                workspace_id=str(task["workspace_id"]),
                task_id=task_id,
                task_prompt=str(task["prompt"]),
            )
            active = self._active_version(conn, project_id)
            preview_id = f"context-preview-{uuid4().hex}"
            now = _now()
            conn.execute(
                """INSERT INTO task_context_update_previews (
                       preview_id, task_id, project_id, context_version_id, created_by_user_id,
                       proposed_fingerprint, proposed_content, source_manifest_json, byte_budget,
                       truncated, created_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    preview_id,
                    task_id,
                    project_id,
                    str(active["context_version_id"]),
                    self._user_id(user),
                    assembly.fingerprint,
                    assembly.content,
                    assembly.source_manifest_json,
                    assembly.byte_budget,
                    int(assembly.truncated),
                    now,
                    _future(DEFAULT_PREVIEW_TTL_SECONDS),
                ),
            )
            current = self._task_snapshot_payload(conn, task)
            conn.commit()
            proposed = self._assembly_payload(
                context_version_id=str(active["context_version_id"]), assembly=assembly
            )
            return {
                "preview_id": preview_id,
                "task_id": task_id,
                "project_id": project_id,
                "created_at": now,
                "current": current,
                "proposed": proposed,
                "diff": self._unified_diff(
                    str(current.get("content", "")),
                    assembly.content,
                ),
            }

    def confirm_task_context_update(
        self,
        task_id: str,
        project_id: str,
        preview_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            self._authorize_task_context_update(conn, task_id, project_id, user)
            actor_user_id = self._user_id(user)
            request = {
                "task_id": task_id,
                "project_id": project_id,
                "preview_id": preview_id,
            }
            cached = self._idempotent_result(
                conn, actor_user_id, "task.context.confirm", idempotency_key, request
            )
            if cached is not None:
                return cached
            preview = conn.execute(
                """SELECT * FROM task_context_update_previews
                   WHERE preview_id = ? AND task_id = ? AND project_id = ?
                     AND created_by_user_id = ?""",
                (preview_id, task_id, project_id, actor_user_id),
            ).fetchone()
            if preview is None:
                raise DomainNotFoundError("task context update preview")
            if str(preview["expires_at"]) < _now():
                raise DomainConflictError("Task Context update preview has expired")
            if preview["confirmed_snapshot_id"] is not None:
                raise DomainConflictError("Task Context update preview was already confirmed")
            assembly = ContextAssembly(
                content=str(preview["proposed_content"]),
                fingerprint=str(preview["proposed_fingerprint"]),
                source_manifest=tuple(_load_json_list(preview["source_manifest_json"])),
                byte_budget=int(preview["byte_budget"]),
                truncated=bool(preview["truncated"]),
            )
            context_version_id = str(preview["context_version_id"])
            snapshot_id = self._insert_snapshot(conn, context_version_id, assembly)
            now = _now()
            conn.execute(
                """UPDATE tasks
                   SET project_context_version_id = ?, project_context_snapshot_id = ?, updated_at = ?
                   WHERE task_id = ?""",
                (context_version_id, snapshot_id, now, task_id),
            )
            # A queued Attempt has not crossed the runtime boundary and must
            # follow the newly confirmed Task pin.  The migration trigger
            # protects started Attempts from any snapshot drift.
            conn.execute(
                """UPDATE agent_task_attempts
                   SET context_snapshot_id = ?
                   WHERE task_id = ? AND status = 'queued'""",
                (snapshot_id, task_id),
            )
            conn.execute(
                """UPDATE task_context_update_previews
                   SET confirmed_snapshot_id = ?, confirmed_at = ? WHERE preview_id = ?""",
                (snapshot_id, now, preview_id),
            )
            result: dict[str, object] = {
                "task_id": task_id,
                "project_id": project_id,
                "context_version_id": context_version_id,
                "context_snapshot_id": snapshot_id,
                "fingerprint": assembly.fingerprint,
                "confirmed_at": now,
            }
            self._store_idempotency(
                conn,
                actor_user_id,
                "task.context.confirm",
                idempotency_key,
                request,
                result,
            )
            self._audit(conn, actor_user_id, "task_context.confirmed", "task", task_id)
            conn.commit()
            return result

    def update_task_context(
        self,
        task_id: str,
        project_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> str:
        """Compatibility wrapper for callers that cannot render a preview UI yet."""

        preview = self.preview_task_context_update(task_id, project_id, user)
        key = idempotency_key or f"internal-context-confirm-{uuid4().hex}"
        result = self.confirm_task_context_update(
            task_id,
            project_id,
            str(preview["preview_id"]),
            user,
            idempotency_key=key,
        )
        return str(result["context_snapshot_id"])

    def task_context(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_owner(task_id, dict(user))
            task = conn.execute(
                """SELECT task_id, project_id, project_context_version_id, project_context_snapshot_id
                   FROM tasks WHERE task_id = ?""",
                (task_id,),
            ).fetchone()
            if task is None:
                raise DomainNotFoundError(task_id)
            return self._task_snapshot_payload(conn, task)

    def _create_active_snapshot_for_task_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        task_id: str,
        task_prompt: str,
    ) -> tuple[str, str]:
        active = self._active_version(conn, project_id)
        version_id = str(active["context_version_id"])
        assembly = self._assemble_for_task(
            conn,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
            task_prompt=task_prompt,
            context_version_id=version_id,
        )
        return self._insert_snapshot(conn, version_id, assembly), version_id

    def _assemble_for_task(
        self,
        conn: sqlite3.Connection,
        *,
        project_id: str,
        workspace_id: str,
        task_id: str,
        task_prompt: str,
        context_version_id: str | None = None,
    ) -> ContextAssembly:
        version = (
            self._version(conn, project_id, context_version_id)
            if context_version_id is not None
            else self._active_version(conn, project_id)
        )
        workspace = conn.execute(
            """SELECT workspace_context, updated_at FROM workspaces
               WHERE workspace_id = ?""",
            (workspace_id,),
        ).fetchone()
        workspace_content = ""
        workspace_version = "missing-workspace-v1"
        if workspace is not None:
            raw_context = workspace["workspace_context"]
            workspace_content = raw_context if isinstance(raw_context, str) else ""
            updated_at = workspace["updated_at"]
            workspace_version = str(updated_at) if updated_at is not None else "workspace-v1"
        sources = (
            self._assembler.platform_source(),
            ContextSource(
                source_type="project_brief",
                source_id=str(version["context_version_id"]),
                source_version=str(version["fingerprint"]),
                label="Project Brief",
                content=str(version["content"]),
            ),
            ContextSource(
                source_type="workspace_context",
                source_id=workspace_id,
                source_version=workspace_version,
                label="Workspace Context",
                content=workspace_content,
            ),
            ContextSource(
                source_type="task_request",
                source_id=task_id,
                source_version=_fingerprint(task_prompt),
                label="Task Request",
                content=task_prompt,
            ),
        )
        return self._assembler.assemble(sources)

    def _insert_snapshot(
        self, conn: sqlite3.Connection, context_version_id: str, assembly: ContextAssembly
    ) -> str:
        snapshot_id = f"snapshot-{uuid4().hex}"
        conn.execute(
            """INSERT INTO context_snapshots (
                   context_snapshot_id, context_version_id, fingerprint, content,
                   source_manifest_json, byte_budget, truncated, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                context_version_id,
                assembly.fingerprint,
                assembly.content,
                assembly.source_manifest_json,
                assembly.byte_budget,
                int(assembly.truncated),
                _now(),
            ),
        )
        return snapshot_id

    @staticmethod
    def _active_version(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT context_version_id, project_id, content, fingerprint, is_active,
                      created_by_user_id, created_at
               FROM project_context_versions WHERE project_id = ? AND is_active = 1""",
            (project_id,),
        ).fetchone()
        if row is None:
            raise DomainNotFoundError("active project context version")
        return row

    @staticmethod
    def _version(conn: sqlite3.Connection, project_id: str, context_version_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT context_version_id, project_id, content, fingerprint, is_active,
                      created_by_user_id, created_at
               FROM project_context_versions
               WHERE project_id = ? AND context_version_id = ?""",
            (project_id, context_version_id),
        ).fetchone()
        if row is None:
            raise DomainNotFoundError("project context version")
        return row

    @staticmethod
    def _task_for_project(conn: sqlite3.Connection, task_id: str, project_id: str) -> sqlite3.Row:
        row = conn.execute(
            """SELECT task_id, project_id, workspace_id, prompt, owner_user_id,
                      project_context_version_id, project_context_snapshot_id
               FROM tasks WHERE task_id = ? AND project_id = ?""",
            (task_id, project_id),
        ).fetchone()
        if row is None:
            raise DomainNotFoundError(task_id)
        return row

    def _authorize_task_context_update(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        project_id: str,
        user: Mapping[str, object],
    ) -> sqlite3.Row:
        auth = DomainAuthorizationService(conn)
        auth.require_project_editor(project_id, dict(user))
        task = self._task_for_project(conn, task_id, project_id)
        auth.require_task_owner(task_id, dict(user))
        return task

    @staticmethod
    def _validate_ranges(
        message_start: int | None,
        message_end: int | None,
        output_start: int | None,
        output_end: int | None,
    ) -> None:
        for start, end, label in (
            (message_start, message_end, "message"),
            (output_start, output_end, "output"),
        ):
            if start is None and end is None:
                continue
            if start is None or end is None or start < 0 or end < start:
                raise DomainConflictError(f"Invalid {label} source range")

    @staticmethod
    def _validate_candidate_provenance(
        conn: sqlite3.Connection,
        *,
        project_id: str,
        source_task_id: str | None,
        source_attempt_id: str | None,
    ) -> None:
        if source_task_id is None and source_attempt_id is None:
            return
        task_id = source_task_id
        if source_attempt_id is not None:
            attempt = conn.execute(
                "SELECT task_id FROM agent_task_attempts WHERE attempt_id = ?", (source_attempt_id,)
            ).fetchone()
            if attempt is None:
                raise DomainNotFoundError("source Task Attempt")
            attempt_task_id = str(attempt["task_id"])
            if task_id is not None and task_id != attempt_task_id:
                raise DomainConflictError("Candidate Task and Attempt provenance do not match")
            task_id = attempt_task_id
        if task_id is None:
            raise DomainConflictError("Candidate provenance requires a Task")
        task = conn.execute("SELECT project_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None or task["project_id"] != project_id:
            raise DomainNotFoundError("source Task")

    @staticmethod
    def _append_candidate(draft: str, candidate: str) -> str:
        if not draft:
            return candidate
        if not candidate:
            return draft
        return f"{draft.rstrip()}\n\n{candidate.lstrip()}"

    @staticmethod
    def _unified_diff(before: str, after: str) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="current-context",
                tofile="proposed-context",
            )
        )

    def _task_snapshot_payload(
        self, conn: sqlite3.Connection, task: sqlite3.Row
    ) -> dict[str, object]:
        snapshot_id = task["project_context_snapshot_id"]
        if isinstance(snapshot_id, str) and snapshot_id:
            snapshot = conn.execute(
                "SELECT * FROM context_snapshots WHERE context_snapshot_id = ?", (snapshot_id,)
            ).fetchone()
            if snapshot is not None:
                return self._snapshot_payload(snapshot)
        version_id = task["project_context_version_id"]
        if isinstance(version_id, str) and version_id:
            version = self._version(conn, str(task["project_id"]), version_id)
            return {
                "context_snapshot_id": None,
                "context_version_id": str(version["context_version_id"]),
                "fingerprint": str(version["fingerprint"]),
                "content": str(version["content"]),
                "source_manifest": [],
                "byte_budget": None,
                "truncated": False,
            }
        return {
            "context_snapshot_id": None,
            "context_version_id": None,
            "fingerprint": None,
            "content": "",
            "source_manifest": [],
            "byte_budget": None,
            "truncated": False,
        }

    @staticmethod
    def _version_payload(row: sqlite3.Row) -> dict[str, object]:
        return {
            "context_version_id": str(row["context_version_id"]),
            "project_id": str(row["project_id"]),
            "content": str(row["content"]),
            "fingerprint": str(row["fingerprint"]),
            "is_active": bool(row["is_active"]),
            "created_by_user_id": str(row["created_by_user_id"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _snapshot_payload(row: sqlite3.Row) -> dict[str, object]:
        return {
            "context_snapshot_id": str(row["context_snapshot_id"]),
            "context_version_id": str(row["context_version_id"]),
            "fingerprint": str(row["fingerprint"]),
            "content": str(row["content"]),
            "source_manifest": _load_json_list(row["source_manifest_json"]),
            "byte_budget": int(row["byte_budget"]) if row["byte_budget"] is not None else None,
            "truncated": bool(row["truncated"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _assembly_payload(
        *, context_version_id: str, assembly: ContextAssembly
    ) -> dict[str, object]:
        return {
            "context_snapshot_id": None,
            "context_version_id": context_version_id,
            "fingerprint": assembly.fingerprint,
            "content": assembly.content,
            "source_manifest": list(assembly.source_manifest),
            "byte_budget": assembly.byte_budget,
            "truncated": assembly.truncated,
        }

    @staticmethod
    def _candidate(conn: sqlite3.Connection, project_id: str, candidate_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM project_context_candidates WHERE candidate_id = ? AND project_id = ?",
            (candidate_id, project_id),
        ).fetchone()
        if row is None:
            raise DomainNotFoundError("project context candidate")
        return row

    @staticmethod
    def _candidate_payload(row: sqlite3.Row | None) -> dict[str, object]:
        if row is None:
            raise DomainNotFoundError("project context candidate")
        return {
            "candidate_id": str(row["candidate_id"]),
            "project_id": str(row["project_id"]),
            "content": str(row["content"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "created_by_user_id": row["created_by_user_id"],
            "source_metadata": _load_json_object(row["source_metadata_json"]),
            "source_task_id": row["source_task_id"],
            "source_attempt_id": row["source_attempt_id"],
            "source_message_start_seq": row["source_message_start_seq"],
            "source_message_end_seq": row["source_message_end_seq"],
            "source_output_start_seq": row["source_output_start_seq"],
            "source_output_end_seq": row["source_output_end_seq"],
            "accepted_by_user_id": row["accepted_by_user_id"],
            "accepted_at": row["accepted_at"],
            "rejected_by_user_id": row["rejected_by_user_id"],
            "rejected_at": row["rejected_at"],
            "rejection_reason": row["rejection_reason"],
        }

    @staticmethod
    def _fragment_payload(row: sqlite3.Row | None) -> dict[str, object]:
        if row is None:
            raise DomainNotFoundError("project context fragment")
        return {
            "fragment_id": str(row["fragment_id"]),
            "project_id": str(row["project_id"]),
            "source_type": str(row["source_type"]),
            "source_version": row["source_version"],
            "source_fingerprint": row["source_fingerprint"],
            "source_metadata": _load_json_object(row["source_metadata_json"]),
            "content": str(row["content"]),
            "sort_order": int(row["sort_order"]),
            "byte_budget": row["byte_budget"],
            "created_by_user_id": row["created_by_user_id"],
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _draft_payload(conn: sqlite3.Connection, project_id: str) -> dict[str, object] | None:
        row = conn.execute(
            "SELECT content, updated_by_user_id, updated_at FROM project_context_drafts WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        content = str(row["content"])
        return {
            "content": content,
            "fingerprint": _fingerprint(content),
            "updated_by_user_id": str(row["updated_by_user_id"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _request_hash(request: Mapping[str, object]) -> str:
        return _fingerprint(_canonical_json(dict(request)))

    def _idempotent_result(
        self,
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        idempotency_key: str,
        request: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not idempotency_key:
            raise DomainConflictError("Idempotency-Key is required")
        row = conn.execute(
            """SELECT request_hash, response_json FROM domain_idempotency_requests
               WHERE actor_user_id = ? AND scope = ? AND idempotency_key = ?""",
            (actor_user_id, scope, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != self._request_hash(request):
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        response = _load_json_object(row["response_json"])
        if not response:
            raise DomainConflictError("Stored idempotency response is invalid")
        return response

    def _store_idempotency(
        self,
        conn: sqlite3.Connection,
        actor_user_id: str,
        scope: str,
        idempotency_key: str,
        request: Mapping[str, object],
        result: Mapping[str, object],
    ) -> None:
        if not idempotency_key:
            raise DomainConflictError("Idempotency-Key is required")
        conn.execute(
            """INSERT INTO domain_idempotency_requests
               (actor_user_id, scope, idempotency_key, request_hash, response_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                actor_user_id,
                scope,
                idempotency_key,
                self._request_hash(request),
                _canonical_json(dict(result)),
                _now(),
            ),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
    ) -> None:
        conn.execute(
            """INSERT INTO domain_audit_events
               (event_id, actor_id, event_type, subject_type, subject_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )
