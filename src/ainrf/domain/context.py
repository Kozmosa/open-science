"""Versioned, auditable Project Context assembly and Task pinning."""

from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
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
from ainrf.domain_telemetry import record_durable_idempotency_event
from ainrf.domain.write_fence import DomainWriteFence
from ainrf.domain_control import MaintenanceModeError

DEFAULT_CONTEXT_BYTE_BUDGET = 32 * 1024
DEFAULT_PREVIEW_TTL_SECONDS = 30 * 60
PLATFORM_CONSTRAINTS_VERSION = "openscience-platform-v1"
DEFAULT_PLATFORM_CONSTRAINTS = (
    "Operate within the selected OpenScience Project and Workspace. "
    "Respect tenant isolation, do not expose credentials or private paths, "
    "and report uncertainty instead of assuming unavailable state."
)
_TASK_CONTEXT_LIFECYCLE_CAPABILITY = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def context_version_fingerprint(
    content: str, fragment_manifest: Sequence[Mapping[str, object]] = ()
) -> str:
    """Return the immutable fingerprint for one published Context Version.

    Context Fragments are executable Context input, not merely UI annotations.
    Including their frozen manifest in the Version fingerprint means two
    otherwise identical Drafts with different reviewed source material cannot
    masquerade as the same Version.  The manifest is intentionally serialized
    canonically so replaying a publish against the same source set is stable.
    """

    return _fingerprint(
        _canonical_json(
            {
                "content": content,
                "fragment_manifest": [dict(item) for item in fragment_manifest],
                "version_format": 1,
            }
        )
    )


def empty_fragment_manifest_json() -> str:
    """Return the canonical empty immutable Fragment manifest."""

    return _canonical_json([])


def verified_fragment_provenance_evidence(
    fragment_manifest: Sequence[Mapping[str, object]],
) -> str:
    """Return audit evidence for a Version published with a reviewed manifest."""

    manifest_json = _canonical_json([dict(item) for item in fragment_manifest])
    return _canonical_json(
        {
            "kind": "published_fragment_manifest",
            "manifest_sha256": _fingerprint(manifest_json),
            "fragment_count": len(fragment_manifest),
            "source": "project_context_publish_transaction",
        }
    )


def unresolved_legacy_fragment_provenance_evidence(*, source: str) -> str:
    """Record that a synthetic/imported Version has no historic association.

    The source model did not persist a Version-to-Fragment mapping, so an
    empty manifest must not be interpreted as proof that historic Context had
    no Fragments.  Callers preserve the Version for audit but require an owner
    to publish a verified successor before it can assemble a new Snapshot.
    """

    return _canonical_json(
        {
            "kind": "legacy_fragment_provenance_unavailable",
            "reason": "No historic Version-to-Fragment association was persisted.",
            "source": source,
        }
    )


def record_context_version_fragment_provenance_in_transaction(
    conn: sqlite3.Connection,
    *,
    context_version_id: str,
    status: str,
    evidence_json: str,
    recorded_at: str,
) -> None:
    """Append immutable Fragment provenance alongside a Context Version."""

    if status not in {"verified", "attention_needed"}:
        raise ValueError("Unknown Context Version fragment provenance status")
    conn.execute(
        """
        INSERT INTO project_context_version_provenance (
            context_version_id, fragment_provenance_status, evidence_json, recorded_at
        ) VALUES (?, ?, ?, ?)
        """,
        (context_version_id, status, evidence_json, recorded_at),
    )


def task_context_lifecycle_capability() -> object:
    """Return the private capability held by ``TaskApplicationService`` only."""

    return _TASK_CONTEXT_LIFECYCLE_CAPABILITY


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
    fragments: tuple[ContextFragment, ...] = ()

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.content)


@dataclass(frozen=True, slots=True)
class ContextFragment:
    """An immutable, provenance-bearing contribution to one Context Source.

    Fragments remain nested below one of the four fixed source groups rather
    than becoming an unbounded fifth source type.  That keeps the assembler's
    public ordering contract stable while preserving the origin and budget of
    manually supplied Project material in every Snapshot manifest.
    """

    fragment_id: str
    source_type: str
    source_version: str
    content: str
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    sort_order: int = 0
    byte_budget: int | None = None
    created_by_user_id: str | None = None
    created_at: str | None = None
    source_fingerprint: str | None = None

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
            source_rendered_bytes = rendered_bytes
            source_included_bytes = included_bytes
            chunks.append(included)
            remaining -= included_bytes

            fragment_manifest: list[dict[str, object]] = []
            for fragment_position, fragment in enumerate(source.fragments):
                if fragment.byte_budget is not None and fragment.byte_budget < 0:
                    raise ValueError("Context Fragment byte budget cannot be negative")
                if (
                    fragment.source_fingerprint is not None
                    and fragment.source_fingerprint != fragment.fingerprint
                ):
                    raise ValueError(
                        "Context Fragment provenance fingerprint does not match content"
                    )

                fragment_budget = fragment.byte_budget
                locally_included_content = (
                    _utf8_prefix(fragment.content, fragment_budget)
                    if fragment_budget is not None
                    else fragment.content
                )
                fragment_input_bytes = len(fragment.content.encode("utf-8"))
                fragment_local_bytes = len(locally_included_content.encode("utf-8"))
                locally_truncated = fragment_local_bytes != fragment_input_bytes
                fragment_rendered = (
                    f"### Context Fragment: {fragment.source_type}\n{locally_included_content}\n\n"
                )
                fragment_rendered_bytes = len(fragment_rendered.encode("utf-8"))
                fragment_included = _utf8_prefix(fragment_rendered, remaining)
                fragment_included_bytes = len(fragment_included.encode("utf-8"))
                globally_truncated = fragment_included_bytes != fragment_rendered_bytes
                fragment_truncated = locally_truncated or globally_truncated
                source_truncated = source_truncated or fragment_truncated
                source_rendered_bytes += fragment_rendered_bytes
                source_included_bytes += fragment_included_bytes
                chunks.append(fragment_included)
                remaining -= fragment_included_bytes
                fragment_manifest.append(
                    {
                        "position": fragment_position,
                        "fragment_id": fragment.fragment_id,
                        "source_type": fragment.source_type,
                        "source_id": fragment.fragment_id,
                        "source_version": fragment.source_version,
                        "fingerprint": fragment.fingerprint,
                        "source_metadata": dict(fragment.source_metadata),
                        "sort_order": fragment.sort_order,
                        "byte_budget": fragment.byte_budget,
                        "created_by_user_id": fragment.created_by_user_id,
                        "created_at": fragment.created_at,
                        "input_bytes": fragment_input_bytes,
                        "local_included_bytes": fragment_local_bytes,
                        "rendered_bytes": fragment_rendered_bytes,
                        "included_bytes": fragment_included_bytes,
                        "locally_truncated": locally_truncated,
                        "globally_truncated": globally_truncated,
                        "truncated": fragment_truncated,
                    }
                )

            truncated = truncated or source_truncated
            manifest.append(
                {
                    "position": position,
                    "source_type": source.source_type,
                    "source_id": source.source_id,
                    "source_version": source.source_version,
                    "fingerprint": source.fingerprint,
                    "input_bytes": len(source.content.encode("utf-8")),
                    "rendered_bytes": source_rendered_bytes,
                    "included_bytes": source_included_bytes,
                    "truncated": source_truncated,
                    "fragments": fragment_manifest,
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
        artifact_sha: str | None = None,
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
        self._write_fence = DomainWriteFence(state_root, artifact_sha=artifact_sha)

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

    @staticmethod
    def _require_task_lifecycle_capability(capability: object | None) -> None:
        if capability is not _TASK_CONTEXT_LIFECYCLE_CAPABILITY:
            raise DomainConflictError(
                "Task Context mutations must be submitted through TaskApplicationService"
            )

    @staticmethod
    def initialize_project_context_in_transaction(
        conn: sqlite3.Connection,
        *,
        project_id: str,
        owner_user_id: str,
        created_at: str,
    ) -> str:
        """Create the empty Draft and initial immutable Active Version atomically.

        A Project is not executable until it has an Active Version.  Keeping
        both Context rows in the Project creation transaction prevents fresh
        Projects from entering a state where a later Task creation can fail
        only because its Context lifecycle was never initialized.
        """

        context_version_id = f"context-{uuid4().hex}"
        content = ""
        fragment_manifest_json = empty_fragment_manifest_json()
        conn.execute(
            """INSERT INTO project_context_drafts
               (project_id, content, updated_by_user_id, updated_at)
               VALUES (?, ?, ?, ?)""",
            (project_id, content, owner_user_id, created_at),
        )
        conn.execute(
            """INSERT INTO project_context_versions
               (context_version_id, project_id, content, fingerprint, fragment_manifest_json,
                is_active, created_by_user_id, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                context_version_id,
                project_id,
                content,
                context_version_fingerprint(content),
                fragment_manifest_json,
                owner_user_id,
                created_at,
            ),
        )
        record_context_version_fragment_provenance_in_transaction(
            conn,
            context_version_id=context_version_id,
            status="verified",
            evidence_json=verified_fragment_provenance_evidence(()),
            recorded_at=created_at,
        )
        return context_version_id

    def save_draft(
        self,
        project_id: str,
        content: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            actor_user_id = self._user_id(user)
            request = {"project_id": project_id, "content": content}
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "project.context.draft.save",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            now = _now()
            conn.execute(
                """INSERT INTO project_context_drafts(project_id, content, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET content = excluded.content,
                       updated_by_user_id = excluded.updated_by_user_id, updated_at = excluded.updated_at""",
                (project_id, content, actor_user_id, now),
            )
            result: dict[str, object] = {
                "project_id": project_id,
                "content": content,
                "fingerprint": _fingerprint(content),
                "updated_by_user_id": actor_user_id,
                "updated_at": now,
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.draft.save",
                    idempotency_key,
                    request,
                    result,
                )
            self._audit(conn, actor_user_id, "project_context.draft_saved", "project", project_id)
            conn.commit()
            return result

    def get_context(self, project_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            auth = DomainAuthorizationService(conn)
            role = auth.require_project_viewer(project_id, dict(user))
            active = self._active_version_or_none(conn, project_id)
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
            fragment_manifest = self._freeze_project_fragments(conn, project_id)
            version_fingerprint = context_version_fingerprint(content, fragment_manifest)
            actor_user_id = self._user_id(user)
            request = {
                "project_id": project_id,
                "draft_fingerprint": _fingerprint(content),
                "fragment_manifest_fingerprint": _fingerprint(
                    _canonical_json(list(fragment_manifest))
                ),
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
                   (context_version_id, project_id, content, fingerprint, fragment_manifest_json,
                    is_active, created_by_user_id, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    version_id,
                    project_id,
                    content,
                    version_fingerprint,
                    _canonical_json(list(fragment_manifest)),
                    actor_user_id,
                    now,
                ),
            )
            record_context_version_fragment_provenance_in_transaction(
                conn,
                context_version_id=version_id,
                status="verified",
                evidence_json=verified_fragment_provenance_evidence(fragment_manifest),
                recorded_at=now,
            )
            result: dict[str, object] = {
                "context_version_id": version_id,
                "project_id": project_id,
                "fingerprint": version_fingerprint,
                "content": content,
                "fragment_manifest": list(fragment_manifest),
                "fragment_provenance_status": "verified",
                "fragment_provenance_evidence": _load_json_object(
                    verified_fragment_provenance_evidence(fragment_manifest)
                ),
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
            rows = self._versions_for_project(conn, project_id)
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
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        self._validate_ranges(
            source_message_start_seq,
            source_message_end_seq,
            source_output_start_seq,
            source_output_end_seq,
        )
        if source_task_id is None:
            raise DomainConflictError("Context Candidate provenance requires a source Task")
        if source_message_start_seq is None and source_output_start_seq is None:
            raise DomainConflictError(
                "Context Candidate provenance requires a message or output source range"
            )
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            auth = DomainAuthorizationService(conn)
            provenance_task_id = self._validate_candidate_provenance(
                conn,
                project_id=project_id,
                source_task_id=source_task_id,
                source_attempt_id=source_attempt_id,
            )
            # A Candidate is a proposal from the author of the selected Task
            # material, not another direct Project Context write path.  The
            # Project owner/editor remains responsible for accepting or
            # rejecting it later.  ``require_task_owner`` preserves the
            # normal 404/403 visibility boundary and admits administrators
            # without granting tenant execution authority.
            auth.require_task_owner(provenance_task_id, dict(user))
            self._validate_candidate_source_ranges(
                conn,
                task_id=provenance_task_id,
                message_start=source_message_start_seq,
                message_end=source_message_end_seq,
                output_start=source_output_start_seq,
                output_end=source_output_end_seq,
            )
            actor_user_id = self._user_id(user)
            canonical_source_metadata = dict(source_metadata or {})
            request: dict[str, object] = {
                "project_id": project_id,
                "content": content,
                "source_metadata": canonical_source_metadata,
                "source_task_id": source_task_id,
                "source_attempt_id": source_attempt_id,
                "source_message_start_seq": source_message_start_seq,
                "source_message_end_seq": source_message_end_seq,
                "source_output_start_seq": source_output_start_seq,
                "source_output_end_seq": source_output_end_seq,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "project.context.candidate.create",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            candidate_id = f"candidate-{uuid4().hex}"
            now = _now()
            conn.execute(
                """INSERT INTO project_context_candidates (
                       candidate_id, project_id, content, status, created_at,
                       created_by_user_id, source_metadata_json, source_task_id,
                       source_attempt_id, source_message_start_seq, source_message_end_seq,
                       source_output_start_seq, source_output_end_seq
                   ) VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    project_id,
                    content,
                    now,
                    actor_user_id,
                    _canonical_json(canonical_source_metadata),
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
                actor_user_id,
                "project_context.candidate_created",
                "candidate",
                candidate_id,
            )
            result = self._candidate_payload(
                conn.execute(
                    "SELECT * FROM project_context_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
            )
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.candidate.create",
                    idempotency_key,
                    request,
                    result,
                )
            conn.commit()
            return result

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
        self,
        project_id: str,
        candidate_id: str,
        user: Mapping[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            actor_user_id = self._user_id(user)
            request = {"project_id": project_id, "candidate_id": candidate_id}
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "project.context.candidate.accept",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            candidate = self._candidate(conn, project_id, candidate_id)
            if candidate["status"] == "rejected":
                raise DomainConflictError("A rejected Context Candidate cannot be accepted")
            draft = conn.execute(
                "SELECT content FROM project_context_drafts WHERE project_id = ?", (project_id,)
            ).fetchone()
            current = str(draft["content"]) if draft is not None else ""
            if candidate["status"] == "accepted":
                result: dict[str, object] = {
                    "candidate": self._candidate_payload(candidate),
                    "draft": self._draft_payload(conn, project_id),
                }
                if idempotency_key is not None:
                    # Compatibility callers may have accepted the Candidate
                    # before the API required a key.  Persist the resulting
                    # replay value without pretending that it was accepted a
                    # second time in the domain audit trail.
                    self._store_idempotency(
                        conn,
                        actor_user_id,
                        "project.context.candidate.accept",
                        idempotency_key,
                        request,
                        result,
                    )
                    self._write_fence.record_first_v2_write(conn, actor_id=actor_user_id)
                    conn.commit()
                return result
            proposed = self._append_candidate(current, str(candidate["content"]))
            now = _now()
            conn.execute(
                """INSERT INTO project_context_drafts(project_id, content, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET content = excluded.content,
                       updated_by_user_id = excluded.updated_by_user_id, updated_at = excluded.updated_at""",
                (project_id, proposed, actor_user_id, now),
            )
            conn.execute(
                """UPDATE project_context_candidates
                   SET status = 'accepted', accepted_by_user_id = ?, accepted_at = ?
                   WHERE candidate_id = ?""",
                (actor_user_id, now, candidate_id),
            )
            self._audit(
                conn,
                actor_user_id,
                "project_context.candidate_accepted",
                "candidate",
                candidate_id,
            )
            updated = self._candidate(conn, project_id, candidate_id)
            result: dict[str, object] = {
                "candidate": self._candidate_payload(updated),
                "draft": self._draft_payload(conn, project_id),
            }
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.candidate.accept",
                    idempotency_key,
                    request,
                    result,
                )
            conn.commit()
            return result

    def reject_candidate(
        self,
        project_id: str,
        candidate_id: str,
        user: Mapping[str, object],
        *,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            DomainAuthorizationService(conn).require_project_editor(project_id, dict(user))
            actor_user_id = self._user_id(user)
            request = {
                "project_id": project_id,
                "candidate_id": candidate_id,
                "reason": reason,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "project.context.candidate.reject",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            candidate = self._candidate(conn, project_id, candidate_id)
            if candidate["status"] == "accepted":
                raise DomainConflictError("An accepted Context Candidate cannot be rejected")
            if candidate["status"] == "rejected":
                result = self._candidate_payload(candidate)
                if idempotency_key is not None:
                    self._store_idempotency(
                        conn,
                        actor_user_id,
                        "project.context.candidate.reject",
                        idempotency_key,
                        request,
                        result,
                    )
                    self._write_fence.record_first_v2_write(conn, actor_id=actor_user_id)
                    conn.commit()
                return result
            now = _now()
            conn.execute(
                """UPDATE project_context_candidates
                   SET status = 'rejected', rejected_by_user_id = ?, rejected_at = ?,
                       rejection_reason = ? WHERE candidate_id = ?""",
                (actor_user_id, now, reason, candidate_id),
            )
            self._audit(
                conn,
                actor_user_id,
                "project_context.candidate_rejected",
                "candidate",
                candidate_id,
            )
            result = self._candidate_payload(self._candidate(conn, project_id, candidate_id))
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.candidate.reject",
                    idempotency_key,
                    request,
                    result,
                )
            conn.commit()
            return result

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
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if not source_type:
            raise DomainConflictError("Context Fragment source_type is required")
        if byte_budget is not None and byte_budget < 0:
            raise DomainConflictError("Context Fragment byte_budget cannot be negative")
        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            # Persisted Fragments participate in future Task Snapshots.  They
            # therefore carry the same publishing authority as an Active
            # Context change; an ordinary editor may still edit a Draft or
            # propose a Candidate, but cannot inject runtime material around
            # the publish gate.
            DomainAuthorizationService(conn).require_project_publisher(project_id, dict(user))
            actor_user_id = self._user_id(user)
            canonical_source_metadata = dict(source_metadata or {})
            request: dict[str, object] = {
                "project_id": project_id,
                "content": content,
                "source_type": source_type,
                "source_metadata": canonical_source_metadata,
                "source_version": source_version,
                "sort_order": sort_order,
                "byte_budget": byte_budget,
            }
            if idempotency_key is not None:
                cached = self._idempotent_result(
                    conn,
                    actor_user_id,
                    "project.context.fragment.create",
                    idempotency_key,
                    request,
                )
                if cached is not None:
                    return cached
            fragment_id = f"fragment-{uuid4().hex}"
            now = _now()
            fingerprint = _fingerprint(content)
            effective_source_version = source_version or fingerprint
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
                    effective_source_version,
                    fingerprint,
                    sort_order,
                    byte_budget,
                    actor_user_id,
                    _canonical_json(canonical_source_metadata),
                ),
            )
            self._audit(
                conn,
                actor_user_id,
                "project_context.fragment_created",
                "fragment",
                fragment_id,
            )
            result = self._fragment_payload(
                conn.execute(
                    "SELECT * FROM project_context_fragments WHERE fragment_id = ?", (fragment_id,)
                ).fetchone()
            )
            if idempotency_key is not None:
                self._store_idempotency(
                    conn,
                    actor_user_id,
                    "project.context.fragment.create",
                    idempotency_key,
                    request,
                    result,
                )
            conn.commit()
            return result

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

    def pin_active_context(
        self,
        task_id: str,
        project_id: str,
        *,
        _lifecycle_capability: object | None = None,
    ) -> str:
        """Retired direct Task-pin facade; only lifecycle code may use it."""

        self._require_task_lifecycle_capability(_lifecycle_capability)

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
            # This compatibility entry point updates a Task without producing
            # a domain audit event.  It must still cross the exact same v2
            # fuse in the caller-owned transaction as normal lifecycle
            # writes, so an unsafe source drift rolls back the new pin.
            self._write_fence.record_first_v2_write(conn, actor_id=str(task["owner_user_id"]))
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

    def ensure_task_snapshot(
        self,
        task_id: str,
        *,
        _lifecycle_capability: object | None = None,
    ) -> str:
        """Retired direct Task-pin facade; only lifecycle code may use it."""

        self._require_task_lifecycle_capability(_lifecycle_capability)

        with closing(self._connect()) as conn:
            self._begin_domain_write(conn)
            snapshot_id = self.ensure_task_snapshot_in_transaction(
                conn,
                task_id,
                _lifecycle_capability=_lifecycle_capability,
            )
            conn.commit()
            return snapshot_id

    def ensure_task_snapshot_in_transaction(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        *,
        _lifecycle_capability: object | None = None,
    ) -> str:
        """Backfill a Task pin using an already-open task/Attempt transaction."""

        self._require_task_lifecycle_capability(_lifecycle_capability)

        task = conn.execute(
            """SELECT task_id, project_id, workspace_id, prompt, project_context_version_id,
                      project_context_snapshot_id, owner_user_id
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
        # This helper is reachable from compatibility services as well as
        # TaskApplicationService.  Record the first v2 write before control
        # returns to either caller so every persisted Task pin is fuse-bound.
        self._write_fence.record_first_v2_write(conn, actor_id=str(task["owner_user_id"]))
        return snapshot_id

    def preview_task_context_update(
        self,
        task_id: str,
        project_id: str,
        user: Mapping[str, object],
        *,
        _lifecycle_capability: object | None = None,
    ) -> dict[str, object]:
        self._require_task_lifecycle_capability(_lifecycle_capability)
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
            # A preview is durable state even though it does not create an
            # audit row.  Bind it to the committed v2 fuse in this same
            # transaction instead of allowing it to become an unguarded first
            # domain write.
            self._write_fence.record_first_v2_write(conn, actor_id=self._user_id(user))
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
        _lifecycle_capability: object | None = None,
    ) -> dict[str, object]:
        self._require_task_lifecycle_capability(_lifecycle_capability)
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
        """Retire the direct Task Context write facade.

        A caller must render a diff and submit it through
        :class:`TaskApplicationService`; generating an internal random key
        here used to bypass both the lifecycle transaction boundary and the
        formal idempotency contract.
        """

        _ = task_id, project_id, user, idempotency_key
        raise DomainConflictError(
            "Task Context mutations must be submitted through TaskApplicationService"
        )

    def task_context(self, task_id: str, user: Mapping[str, object]) -> dict[str, object]:
        with closing(self._connect()) as conn:
            DomainAuthorizationService(conn).require_task_viewer(task_id, dict(user))
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
        fragments = self._fragments_for_version(version)
        sources = (
            self._assembler.platform_source(),
            ContextSource(
                source_type="project_brief",
                source_id=str(version["context_version_id"]),
                source_version=str(version["fingerprint"]),
                label="Project Brief",
                content=str(version["content"]),
                fragments=fragments,
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

    @staticmethod
    def _freeze_project_fragments(
        conn: sqlite3.Connection, project_id: str
    ) -> tuple[dict[str, object], ...]:
        """Capture the complete reviewed Fragment set into a Version manifest.

        This is called only while publishing inside the Project Context write
        transaction.  Future Fragment rows are deliberately not consulted
        when a Task assembles an already-published Version.
        """

        rows = conn.execute(
            """SELECT * FROM project_context_fragments WHERE project_id = ?
               ORDER BY sort_order, created_at, fragment_id""",
            (project_id,),
        ).fetchall()
        frozen: list[dict[str, object]] = []
        for row in rows:
            content = str(row["content"])
            source_fingerprint = row["source_fingerprint"]
            fingerprint = (
                str(source_fingerprint)
                if isinstance(source_fingerprint, str) and source_fingerprint
                else _fingerprint(content)
            )
            frozen.append(
                {
                    "fragment_id": str(row["fragment_id"]),
                    "source_type": str(row["source_type"]),
                    "source_version": (
                        str(row["source_version"])
                        if isinstance(row["source_version"], str) and row["source_version"]
                        else fingerprint
                    ),
                    "content": content,
                    "source_metadata": _load_json_object(row["source_metadata_json"]),
                    "sort_order": int(row["sort_order"]),
                    "byte_budget": (
                        int(row["byte_budget"]) if row["byte_budget"] is not None else None
                    ),
                    "created_by_user_id": (
                        str(row["created_by_user_id"])
                        if isinstance(row["created_by_user_id"], str)
                        else None
                    ),
                    "created_at": str(row["created_at"]),
                    "source_fingerprint": fingerprint,
                }
            )
        return tuple(frozen)

    @staticmethod
    def _fragments_for_version(version: sqlite3.Row) -> tuple[ContextFragment, ...]:
        """Decode the immutable Fragment manifest stored with a Context Version.

        A corrupt manifest is a control-plane integrity failure.  Falling back
        to the mutable Project fragment table would reintroduce Context drift,
        so the caller receives a precise conflict instead.
        """

        provenance_status = version["fragment_provenance_status"]
        if provenance_status != "verified":
            raise DomainConflictError(
                "Context Version Fragment provenance needs explicit review before a new Snapshot"
            )
        raw_manifest = version["fragment_manifest_json"]
        if not isinstance(raw_manifest, str):
            raise DomainConflictError("Context Version fragment manifest is missing")
        try:
            decoded = json.loads(raw_manifest)
        except json.JSONDecodeError as exc:
            raise DomainConflictError("Context Version fragment manifest is invalid") from exc
        if not isinstance(decoded, list):
            raise DomainConflictError("Context Version fragment manifest is invalid")
        fragments: list[ContextFragment] = []
        for entry in decoded:
            if not isinstance(entry, dict):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            content = entry.get("content")
            fragment_id = entry.get("fragment_id")
            source_type = entry.get("source_type")
            source_version = entry.get("source_version")
            source_fingerprint = entry.get("source_fingerprint")
            created_at = entry.get("created_at")
            if not all(
                isinstance(value, str) and value
                for value in (
                    content,
                    fragment_id,
                    source_type,
                    source_version,
                    source_fingerprint,
                    created_at,
                )
            ):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            metadata = entry.get("source_metadata", {})
            if not isinstance(metadata, dict):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            sort_order = entry.get("sort_order", 0)
            byte_budget = entry.get("byte_budget")
            created_by_user_id = entry.get("created_by_user_id")
            if isinstance(sort_order, bool) or not isinstance(sort_order, int):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            if byte_budget is not None and (
                isinstance(byte_budget, bool) or not isinstance(byte_budget, int)
            ):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            if created_by_user_id is not None and not isinstance(created_by_user_id, str):
                raise DomainConflictError("Context Version fragment manifest is invalid")
            if source_fingerprint != _fingerprint(content):
                raise DomainConflictError(
                    "Context Version fragment manifest fingerprint is invalid"
                )
            fragments.append(
                ContextFragment(
                    fragment_id=fragment_id,
                    source_type=source_type,
                    source_version=source_version,
                    content=content,
                    source_metadata={str(key): value for key, value in metadata.items()},
                    sort_order=sort_order,
                    byte_budget=byte_budget,
                    created_by_user_id=created_by_user_id,
                    created_at=created_at,
                    source_fingerprint=source_fingerprint,
                )
            )
        return tuple(fragments)

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
    def _active_version_or_none(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT version.context_version_id, version.project_id, version.content,
                   version.fingerprint, version.fragment_manifest_json, version.is_active,
                   version.created_by_user_id, version.created_at,
                   COALESCE(provenance.fragment_provenance_status, 'attention_needed')
                       AS fragment_provenance_status,
                   COALESCE(provenance.evidence_json, '{}')
                       AS fragment_provenance_evidence_json
            FROM project_context_versions AS version
            LEFT JOIN project_context_version_provenance AS provenance
              ON provenance.context_version_id = version.context_version_id
            WHERE version.project_id = ? AND version.is_active = 1
            """,
            (project_id,),
        ).fetchone()

    @classmethod
    def _active_version(cls, conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = cls._active_version_or_none(conn, project_id)
        if row is None:
            raise DomainNotFoundError("active project context version")
        return row

    @staticmethod
    def _version(conn: sqlite3.Connection, project_id: str, context_version_id: str) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT version.context_version_id, version.project_id, version.content,
                   version.fingerprint, version.fragment_manifest_json, version.is_active,
                   version.created_by_user_id, version.created_at,
                   COALESCE(provenance.fragment_provenance_status, 'attention_needed')
                       AS fragment_provenance_status,
                   COALESCE(provenance.evidence_json, '{}')
                       AS fragment_provenance_evidence_json
            FROM project_context_versions AS version
            LEFT JOIN project_context_version_provenance AS provenance
              ON provenance.context_version_id = version.context_version_id
            WHERE version.project_id = ? AND version.context_version_id = ?
            """,
            (project_id, context_version_id),
        ).fetchone()
        if row is None:
            raise DomainNotFoundError("project context version")
        return row

    @staticmethod
    def _versions_for_project(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT version.context_version_id, version.project_id, version.content,
                   version.fingerprint, version.fragment_manifest_json, version.is_active,
                   version.created_by_user_id, version.created_at,
                   COALESCE(provenance.fragment_provenance_status, 'attention_needed')
                       AS fragment_provenance_status,
                   COALESCE(provenance.evidence_json, '{}')
                       AS fragment_provenance_evidence_json
            FROM project_context_versions AS version
            LEFT JOIN project_context_version_provenance AS provenance
              ON provenance.context_version_id = version.context_version_id
            WHERE version.project_id = ?
            ORDER BY version.created_at DESC, version.context_version_id DESC
            """,
            (project_id,),
        ).fetchall()

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
        source_task_id: str,
        source_attempt_id: str | None,
    ) -> str:
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
        task = conn.execute("SELECT project_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if task is None or task["project_id"] != project_id:
            raise DomainNotFoundError("source Task")
        return task_id

    @staticmethod
    def _validate_candidate_source_ranges(
        conn: sqlite3.Connection,
        *,
        task_id: str,
        message_start: int | None,
        message_end: int | None,
        output_start: int | None,
        output_end: int | None,
    ) -> None:
        """Reject a Candidate that points at non-persisted Task material.

        Task output sequence numbers are assigned by the durable Task writer.
        Checking that every selected inclusive range is present prevents a
        caller from manufacturing provenance for an arbitrary message or
        result while still permitting either a message selection or an output
        selection (or both).
        """

        for start, end, label in (
            (message_start, message_end, "message"),
            (output_start, output_end, "output"),
        ):
            if start is None or end is None:
                continue
            row = conn.execute(
                """SELECT COUNT(*) AS selected_count
                   FROM task_outputs
                   WHERE task_id = ? AND seq BETWEEN ? AND ?""",
                (task_id, start, end),
            ).fetchone()
            selected_count = int(row["selected_count"]) if row is not None else 0
            if selected_count != end - start + 1:
                raise DomainConflictError(
                    f"Context Candidate {label} source range is not persisted for the Task"
                )

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
        provenance_status = row["fragment_provenance_status"]
        evidence = _load_json_object(row["fragment_provenance_evidence_json"])
        return {
            "context_version_id": str(row["context_version_id"]),
            "project_id": str(row["project_id"]),
            "content": str(row["content"]),
            "fingerprint": str(row["fingerprint"]),
            "fragment_manifest": _load_json_list(row["fragment_manifest_json"]),
            "fragment_provenance_status": str(provenance_status),
            "fragment_provenance_evidence": evidence,
            "assembly_eligible": provenance_status == "verified",
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
            record_durable_idempotency_event(
                "conflict",
                actor_user_id=actor_user_id,
                scope=scope,
                idempotency_key=idempotency_key,
                request=request,
            )
            raise DomainConflictError("Idempotency-Key was already used for a different request")
        response = _load_json_object(row["response_json"])
        if not response:
            raise DomainConflictError("Stored idempotency response is invalid")
        record_durable_idempotency_event(
            "reused",
            actor_user_id=actor_user_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request=request,
            response=response,
        )
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

    def _audit(
        self,
        conn: sqlite3.Connection,
        actor_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
    ) -> None:
        self._write_fence.record_first_v2_write(conn, actor_id=actor_id)
        conn.execute(
            """INSERT INTO domain_audit_events
               (event_id, actor_id, event_type, subject_type, subject_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid4().hex, actor_id, event_type, subject_type, subject_id, _now()),
        )
