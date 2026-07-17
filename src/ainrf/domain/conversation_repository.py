"""Transaction-neutral SQLite persistence for canonical conversations.

Application services own authorization, transaction boundaries, idempotency, and
provider acceptance. This repository only exposes the SQL primitives needed to
persist accepted Turns, append canonical Items, and maintain Task-scoped engine
conversation bindings.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3


class SqliteConversationRepository:
    """SQL-only repository for TaskTurn, TurnItem, and binding records."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_task_authority(self, *, task_id: str, created_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO conversation_task_authorities (task_id, authority, created_at)
            VALUES (?, 'conversation_v3', ?)
            """,
            (task_id, created_at),
        )

    def task_authority(self, task_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT authority FROM conversation_task_authorities WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return None if row is None else str(row["authority"])

    def insert_task_state(self, *, task_id: str, created_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO conversation_task_states (
                task_id, work_status, revision, created_at, updated_at
            ) VALUES (?, 'open', 1, ?, ?)
            """,
            (task_id, created_at, created_at),
        )

    def task_state(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM conversation_task_states WHERE task_id = ?", (task_id,)
        ).fetchone()

    def task_harness_engine(self, task_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT harness_engine FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return None if row is None else str(row["harness_engine"])

    def update_work_status(
        self,
        *,
        task_id: str,
        expected_status: str,
        status: str,
        updated_at: str,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE conversation_task_states
            SET work_status = ?, revision = revision + 1, updated_at = ?
            WHERE task_id = ? AND work_status = ?
            """,
            (status, updated_at, task_id, expected_status),
        ).rowcount

    def next_turn_seq(self, task_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn_seq), 0) + 1 FROM task_turns WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def insert_turn(
        self,
        *,
        turn_id: str,
        task_id: str,
        turn_seq: int,
        status: str,
        retry_of_turn_id: str | None,
        context_snapshot_ref: str | None,
        binding_id: str | None,
        engine_family: str,
        engine_driver: str,
        contract_version: int,
        provider_profile_ref: str | None,
        provider_profile_version: str | None,
        provider_profile_fingerprint: str | None,
        model: str | None,
        native_turn_kind: str | None,
        native_turn_ref: str | None,
        accepted_at: str,
        started_at: str | None,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO task_turns (
                turn_id, task_id, turn_seq, status, retry_of_turn_id,
                context_snapshot_ref, binding_id, engine_family, engine_driver,
                contract_version, provider_profile_ref, provider_profile_version,
                provider_profile_fingerprint, model, native_turn_kind,
                native_turn_ref, accepted_at, started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                task_id,
                turn_seq,
                status,
                retry_of_turn_id,
                context_snapshot_ref,
                binding_id,
                engine_family,
                engine_driver,
                contract_version,
                provider_profile_ref,
                provider_profile_version,
                provider_profile_fingerprint,
                model,
                native_turn_kind,
                native_turn_ref,
                accepted_at,
                started_at,
                updated_at,
            ),
        )

    def finish_turn(
        self,
        *,
        turn_id: str,
        status: str,
        finished_at: str,
        updated_at: str,
        failure_code: str | None = None,
        failure_metadata_json: str = "{}",
    ) -> int:
        return self._conn.execute(
            """
            UPDATE task_turns
            SET status = ?, finished_at = ?, updated_at = ?, failure_code = ?,
                failure_metadata_json = ?
            WHERE turn_id = ? AND status = 'in_progress'
            """,
            (
                status,
                finished_at,
                updated_at,
                failure_code,
                failure_metadata_json,
                turn_id,
            ),
        ).rowcount

    def active_turn(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM task_turns WHERE task_id = ? AND status = 'in_progress'",
            (task_id,),
        ).fetchone()

    def turn_by_id(self, turn_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM task_turns WHERE turn_id = ?", (turn_id,)
        ).fetchone()

    def list_turns(self, task_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM task_turns WHERE task_id = ? ORDER BY turn_seq",
            (task_id,),
        ).fetchall()

    def next_task_item_seq(self, task_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(task_item_seq), 0) + 1 FROM turn_items WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def next_turn_item_seq(self, turn_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn_item_seq), 0) + 1 FROM turn_items WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def insert_turn_item(
        self,
        *,
        item_id: str,
        task_id: str,
        turn_id: str,
        task_item_seq: int,
        turn_item_seq: int,
        envelope_type: str,
        envelope_version: int,
        item_type: str,
        actor: str,
        payload_json: str,
        native_provenance_json: str,
        native_dedupe_scope: str | None,
        native_item_id: str | None,
        parent_item_id: str | None,
        call_item_id: str | None,
        occurred_at: str | None,
        ingested_at: str,
        persisted_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO turn_items (
                item_id, task_id, turn_id, task_item_seq, turn_item_seq,
                envelope_type, envelope_version, item_type, actor, payload_json,
                native_provenance_json, native_dedupe_scope, native_item_id,
                parent_item_id, call_item_id, occurred_at, ingested_at, persisted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                task_id,
                turn_id,
                task_item_seq,
                turn_item_seq,
                envelope_type,
                envelope_version,
                item_type,
                actor,
                payload_json,
                native_provenance_json,
                native_dedupe_scope,
                native_item_id,
                parent_item_id,
                call_item_id,
                occurred_at,
                ingested_at,
                persisted_at,
            ),
        )

    def list_turn_items(self, turn_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM turn_items WHERE turn_id = ? ORDER BY turn_item_seq",
            (turn_id,),
        ).fetchall()

    def list_task_items(self, task_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM turn_items WHERE task_id = ? ORDER BY task_item_seq",
            (task_id,),
        ).fetchall()

    def transcript_revision(self, task_id: str) -> str:
        turns = [dict(row) for row in self.list_turns(task_id)]
        items = [dict(row) for row in self.list_task_items(task_id)]
        payload = json.dumps(
            {"turns": turns, "items": items},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def next_binding_seq(self, task_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(MAX(binding_seq), 0) + 1
            FROM engine_conversation_bindings WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def insert_binding(
        self,
        *,
        binding_id: str,
        task_id: str,
        binding_seq: int,
        engine_family: str,
        engine_driver: str,
        native_conversation_kind: str,
        native_conversation_ref: str,
        contract_version: int,
        provider_profile_ref: str | None,
        provider_profile_version: str | None,
        provider_profile_fingerprint: str | None,
        provenance_json: str,
        validation_evidence_json: str,
        created_at: str,
        validated_at: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO engine_conversation_bindings (
                binding_id, task_id, binding_seq, status, engine_family,
                engine_driver, native_conversation_kind, native_conversation_ref,
                contract_version, provider_profile_ref, provider_profile_version,
                provider_profile_fingerprint, provenance_json,
                validation_evidence_json, created_at, validated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding_id,
                task_id,
                binding_seq,
                engine_family,
                engine_driver,
                native_conversation_kind,
                native_conversation_ref,
                contract_version,
                provider_profile_ref,
                provider_profile_version,
                provider_profile_fingerprint,
                provenance_json,
                validation_evidence_json,
                created_at,
                validated_at,
            ),
        )

    def active_binding(self, task_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM engine_conversation_bindings
            WHERE task_id = ? AND status = 'active'
            """,
            (task_id,),
        ).fetchone()

    def supersede_binding(
        self,
        *,
        binding_id: str,
        superseded_at: str,
        validation_evidence_json: str,
    ) -> int:
        return self._conn.execute(
            """
            UPDATE engine_conversation_bindings
            SET status = 'superseded', superseded_at = ?,
                validation_evidence_json = ?
            WHERE binding_id = ? AND status = 'active'
            """,
            (superseded_at, validation_evidence_json, binding_id),
        ).rowcount
