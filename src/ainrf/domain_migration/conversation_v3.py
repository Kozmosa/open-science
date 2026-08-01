"""Standalone legacy-to-Conversation migration Module.

The Interface is intentionally file-oriented: callers provide an immutable
source snapshot and an isolated destination generation.  Serve and worker code
never import or invoke this Module.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid5, NAMESPACE_URL

from ainrf.db import connect, run_pending

_ACTIVE_LEGACY = frozenset({"starting", "running", "paused", "launch_unknown"})
_SECRET_COLUMNS = ("api_key", "codex_api_key")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _id(kind: str, source_hash: str, source_id: str) -> str:
    return uuid5(NAMESPACE_URL, f"openscience:conversation-v3:{source_hash}:{kind}:{source_id}").hex


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class ConversationMigrationManifest:
    source_path: str
    source_sha256: str
    source_size: int
    source_mtime_ns: int
    schema_version: int
    task_count: int
    attempt_count: int
    output_count: int
    active_legacy_count: int
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class FileCredentialStore:
    """Minimal staging CredentialStore Adapter with owner-only permissions."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)

    def put(self, *, reference: str, value: str) -> None:
        target = self._root / reference
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)


class ConversationV3Migration:
    """Deep migration Module for inspect/dry-run/execute/verify/cutover."""

    def inspect(self, source: Path) -> dict[str, object]:
        manifest = self.capture_manifest(source)
        return {
            "manifest": manifest.as_dict(),
            "ready": manifest.active_legacy_count == 0,
            "blockers": (
                [] if manifest.active_legacy_count == 0 else ["active_or_unknown_legacy_execution"]
            ),
        }

    def dry_run(self, source: Path) -> dict[str, object]:
        manifest = self.capture_manifest(source)
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            plan = self._plan(conn)
        return {
            "manifest": manifest.as_dict(),
            "ready": manifest.active_legacy_count == 0,
            "task_count": len(plan),
            "turn_count": sum(len(cast(Sequence[object], item["turns"])) for item in plan),
            "ambiguous_turn_count": sum(
                turn["confidence"] == "ambiguous"
                for item in plan
                for turn in cast(Sequence[Mapping[str, object]], item["turns"])
            ),
        }

    def execute(
        self,
        source: Path,
        destination: Path,
        *,
        artifact_sha: str,
    ) -> dict[str, object]:
        if destination.exists():
            raise ValueError("destination generation already exists")
        manifest = self.capture_manifest(source)
        if manifest.active_legacy_count:
            raise ValueError("active or unknown legacy execution blocks migration")
        destination.parent.mkdir(parents=True, exist_ok=True)
        credential_store = FileCredentialStore(
            destination.parent / f"{destination.name}.credentials"
        )
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as source_conn:
            source_conn.row_factory = sqlite3.Row
            plan = self._plan(source_conn)
            with closing(connect(destination)) as destination_conn:
                source_conn.backup(destination_conn)
                self._scrub_credentials(destination_conn, credential_store, manifest.source_sha256)
                run_pending(destination_conn, "agentic_researcher")
                destination_conn.execute("BEGIN IMMEDIATE")
                self._apply_plan(destination_conn, plan, manifest.source_sha256)
                destination_conn.commit()
                destination_conn.execute("VACUUM")
        if _sha256(source) != manifest.source_sha256:
            raise ValueError("source snapshot changed during migration")
        report: dict[str, object] = {
            "manifest": manifest.as_dict(),
            "artifact_sha": artifact_sha,
            "destination": str(destination),
            "task_count": len(plan),
            "turn_count": sum(len(cast(Sequence[object], item["turns"])) for item in plan),
            "completed_at": _now(),
        }
        report_path = destination.with_suffix(destination.suffix + ".conversation-v3.json")
        report_path.write_text(_json(report), encoding="utf-8")
        return report

    def verify(self, source: Path, destination: Path) -> dict[str, object]:
        manifest = self.capture_manifest(source)
        if not destination.is_file():
            raise ValueError("destination generation does not exist")
        with closing(connect(destination)) as conn:
            run_pending(conn, "agentic_researcher")
            task_count = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
            authority_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM conversation_task_authorities "
                    "WHERE authority = 'conversation_v3'"
                ).fetchone()[0]
            )
            secret_count = 0
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
            for column in _SECRET_COLUMNS:
                if column in columns:
                    secret_count += int(
                        conn.execute(
                            f"SELECT COUNT(*) FROM tasks WHERE {column} IS NOT NULL "
                            f"AND trim({column}) != ''"
                        ).fetchone()[0]
                    )
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        ready = (
            manifest.active_legacy_count == 0
            and task_count == manifest.task_count
            and authority_count == task_count
            and secret_count == 0
            and integrity == "ok"
        )
        return {
            "ready": ready,
            "source_sha256": manifest.source_sha256,
            "task_count": task_count,
            "authority_count": authority_count,
            "secret_count": secret_count,
            "integrity_check": integrity,
        }

    def cutover(self, source: Path, destination: Path, pointer: Path) -> dict[str, object]:
        verification = self.verify(source, destination)
        if not verification["ready"]:
            raise ValueError("verified Conversation generation is required for cutover")
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temporary = pointer.with_name(f".{pointer.name}.{os.getpid()}.tmp")
        temporary.write_text(
            _json(
                {
                    "generation": str(destination.resolve()),
                    "source_sha256": verification["source_sha256"],
                    "cutover_at": _now(),
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, pointer)
        return {"active_generation": str(destination.resolve()), "pointer": str(pointer)}

    @staticmethod
    def capture_manifest(source: Path) -> ConversationMigrationManifest:
        if not source.is_file():
            raise ValueError("source snapshot must be an existing SQLite file")
        stat = source.stat()
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as conn:
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            counts = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("tasks", "agent_task_attempts", "task_outputs")
            }
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_runtime_sessions "
                    f"WHERE status IN ({','.join('?' for _ in _ACTIVE_LEGACY)})",
                    tuple(sorted(_ACTIVE_LEGACY)),
                ).fetchone()[0]
            )
        return ConversationMigrationManifest(
            source_path=str(source.resolve()),
            source_sha256=_sha256(source),
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            schema_version=schema_version,
            task_count=counts["tasks"],
            attempt_count=counts["agent_task_attempts"],
            output_count=counts["task_outputs"],
            active_legacy_count=active,
            created_at=_now(),
        )

    @staticmethod
    def _plan(conn: sqlite3.Connection) -> list[dict[str, object]]:
        plan: list[dict[str, object]] = []
        tasks = conn.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
        for task in tasks:
            task_id = str(task["task_id"])
            attempts = conn.execute(
                "SELECT * FROM agent_task_attempts WHERE task_id = ? "
                "ORDER BY attempt_seq, created_at, attempt_id",
                (task_id,),
            ).fetchall()
            outputs = conn.execute(
                "SELECT * FROM task_outputs WHERE task_id = ? ORDER BY seq", (task_id,)
            ).fetchall()
            turns: list[dict[str, object]] = []
            if attempts:
                for attempt in attempts:
                    trigger = str(attempt["trigger"])
                    if trigger == "resume" and turns:
                        cast(list[str], turns[-1]["runtime_attempt_ids"]).append(
                            str(attempt["attempt_id"])
                        )
                        continue
                    turns.append(
                        {
                            "source_id": str(attempt["attempt_id"]),
                            "status": str(attempt["status"]),
                            "created_at": str(attempt["created_at"]),
                            "started_at": attempt["started_at"],
                            "finished_at": attempt["finished_at"],
                            "retry": trigger == "retry",
                            "confidence": "high" if trigger in {"initial", "retry"} else "inferred",
                            "runtime_attempt_ids": [str(attempt["attempt_id"])],
                        }
                    )
            elif outputs:
                turns.append(
                    {
                        "source_id": f"output:{task_id}",
                        "status": str(task["status"]),
                        "created_at": str(task["created_at"]),
                        "started_at": task["started_at"],
                        "finished_at": task["completed_at"],
                        "retry": False,
                        "confidence": "ambiguous",
                        "runtime_attempt_ids": [],
                    }
                )
            plan.append({"task": dict(task), "turns": turns, "outputs": [dict(x) for x in outputs]})
        return plan

    @staticmethod
    def _scrub_credentials(
        conn: sqlite3.Connection, store: FileCredentialStore, source_hash: str
    ) -> None:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        for column in _SECRET_COLUMNS:
            if column not in columns:
                continue
            rows = conn.execute(
                f"SELECT task_id, {column} FROM tasks WHERE {column} IS NOT NULL "
                f"AND trim({column}) != ''"
            ).fetchall()
            for row in rows:
                reference = _id("credential", source_hash, f"{row['task_id']}:{column}")
                store.put(reference=reference, value=str(row[column]))
            conn.execute(f"UPDATE tasks SET {column} = NULL")
        conn.commit()

    @staticmethod
    def _apply_plan(
        conn: sqlite3.Connection, plan: Sequence[Mapping[str, object]], source_hash: str
    ) -> None:
        for entry in plan:
            task = cast(Mapping[str, object], entry["task"])
            task_id = str(task["task_id"])
            if (
                conn.execute(
                    "SELECT 1 FROM conversation_task_authorities WHERE task_id = ?", (task_id,)
                ).fetchone()
                is not None
            ):
                continue
            timestamp = str(task["updated_at"])
            conn.execute(
                "INSERT INTO conversation_task_authorities"
                "(task_id, authority, created_at) VALUES (?, 'conversation_v3', ?)",
                (task_id, timestamp),
            )
            legacy_status = str(task["status"])
            work_status = (
                "completed"
                if legacy_status == "succeeded"
                else "cancelled"
                if legacy_status in {"cancelled", "stopped"}
                else "open"
            )
            conn.execute(
                "INSERT INTO conversation_task_states"
                "(task_id, work_status, revision, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                (task_id, work_status, str(task["created_at"]), timestamp),
            )
            previous_turn_id: str | None = None
            for turn_seq, raw_turn in enumerate(
                cast(Sequence[Mapping[str, object]], entry["turns"]), start=1
            ):
                source_id = str(raw_turn["source_id"])
                turn_id = _id("turn", source_hash, source_id)
                legacy_turn_status = str(raw_turn["status"])
                status = (
                    "completed"
                    if legacy_turn_status == "succeeded"
                    else "interrupted"
                    if legacy_turn_status in {"cancelled", "stopped", "paused"}
                    else "failed"
                )
                finished_at = raw_turn["finished_at"] or timestamp
                failure_code = "legacy_execution_failed" if status == "failed" else None
                driver = str(task["harness_engine"])
                family = "codex" if driver == "codex-app-server" else "claude"
                if driver not in {"codex-app-server", "claude-code", "agent-sdk"}:
                    driver = "agent-sdk"
                conn.execute(
                    """INSERT INTO task_turns (
                        turn_id, task_id, turn_seq, status, retry_of_turn_id,
                        engine_family, engine_driver, contract_version, accepted_at,
                        started_at, finished_at, updated_at, failure_code,
                        failure_metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                    (
                        turn_id,
                        task_id,
                        turn_seq,
                        status,
                        previous_turn_id if bool(raw_turn["retry"]) else None,
                        family,
                        driver,
                        str(raw_turn["created_at"]),
                        raw_turn["started_at"],
                        finished_at,
                        timestamp,
                        failure_code,
                        _json(
                            {
                                "boundary_source": "legacy_attempt",
                                "boundary_confidence": raw_turn["confidence"],
                                "legacy_attempt_ids": raw_turn["runtime_attempt_ids"],
                                "source_sha256": source_hash,
                            }
                        ),
                    ),
                )
                previous_turn_id = turn_id
            turns = conn.execute(
                "SELECT turn_id FROM task_turns WHERE task_id = ? ORDER BY turn_seq", (task_id,)
            ).fetchall()
            if not turns:
                continue
            target_turn_id = str(turns[-1]["turn_id"])
            for item_seq, output in enumerate(
                cast(Sequence[Mapping[str, object]], entry["outputs"]), start=1
            ):
                item_type = {
                    "message": "agent_message",
                    "thinking": "reasoning_summary",
                    "tool_call": "tool_call",
                    "tool_result": "tool_result",
                    "stderr": "error",
                }.get(str(output["kind"]), "system_notice")
                actor = "agent" if item_type in {"agent_message", "reasoning_summary"} else "system"
                conn.execute(
                    """INSERT INTO turn_items (
                        item_id, task_id, turn_id, task_item_seq, turn_item_seq,
                        envelope_type, envelope_version, item_type, actor, payload_json,
                        native_provenance_json, occurred_at, ingested_at, persisted_at
                    ) VALUES (?, ?, ?, ?, ?, 'legacy_inferred', 1, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _id("item", source_hash, f"{task_id}:{output['seq']}"),
                        task_id,
                        target_turn_id,
                        item_seq,
                        item_seq,
                        item_type,
                        actor,
                        _json({"legacy_kind": output["kind"], "content": output["content"]}),
                        _json(
                            {
                                "source": "task_outputs",
                                "source_seq": output["seq"],
                                "confidence": "legacy_inferred",
                                "source_sha256": source_hash,
                            }
                        ),
                        output["created_at"],
                        output["created_at"],
                        output["created_at"],
                    ),
                )
