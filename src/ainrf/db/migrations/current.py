"""Fresh-install schema baselines for the current product shape."""

from __future__ import annotations

from importlib.resources import files
import sqlite3

from ainrf.db.migration import _has_table, registry


_BASELINE_VERSIONS = {
    "agentic_researcher": 33,
    "auth": 7,
    "literature": 7,
    "terminal": 1,
}
_RETIRED_LITERATURE_TABLES = ("literature_task_sagas",)


def _apply_baseline(conn: sqlite3.Connection, database_name: str) -> None:
    """Execute baseline statements without ``executescript``'s implicit commit."""

    resource = files("ainrf.db.baselines").joinpath(f"{database_name}.sql")
    script = resource.read_text(encoding="utf-8")
    statement: list[str] = []
    for character in script:
        statement.append(character)
        if character != ";":
            continue
        candidate = "".join(statement)
        if not sqlite3.complete_statement(candidate):
            continue
        conn.execute(candidate)
        statement.clear()
    trailing = "".join(statement)
    if trailing.strip():
        conn.execute(trailing)


@registry.register("agentic_researcher")
def migration_034_conversation_cancellation_guards(conn: sqlite3.Connection) -> None:
    """Allow promoted next-Turn reservations to transition from ready to cancelled."""

    conn.execute("DROP TRIGGER IF EXISTS next_turn_transition_guard")
    conn.execute(
        """
        CREATE TRIGGER next_turn_transition_guard
            BEFORE UPDATE OF status ON next_turn_submissions
            WHEN NOT (
                (OLD.status = 'waiting' AND NEW.status IN ('ready', 'cancelled'))
                OR (OLD.status = 'ready' AND NEW.status = 'cancelled')
            )
            BEGIN SELECT RAISE(ABORT, 'invalid next-Turn submission transition'); END
        """
    )


@registry.register("agentic_researcher")
def migration_035_context_snapshot_provenance(conn: sqlite3.Connection) -> None:
    """Persist whether a queued submission inherited or overrode its Task pin."""

    columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(turn_submissions)").fetchall()
    }
    if "context_snapshot_source" in columns:
        return
    conn.execute(
        """ALTER TABLE turn_submissions
           ADD COLUMN context_snapshot_source TEXT NOT NULL DEFAULT 'task_pin'
           CHECK (context_snapshot_source IN ('task_pin', 'submission_override'))"""
    )


@registry.register("agentic_researcher")
def migration_036_retire_legacy_task_status(conn: sqlite3.Connection) -> None:
    """Remove the superseded Task lifecycle shadow after Conversation cutover."""

    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
    if "status" not in columns:
        return
    missing_authority = conn.execute(
        """
        SELECT task.task_id
        FROM tasks AS task
        LEFT JOIN conversation_task_authorities AS authority
          ON authority.task_id = task.task_id AND authority.authority = 'conversation_v3'
        LEFT JOIN conversation_task_states AS state ON state.task_id = task.task_id
        WHERE authority.task_id IS NULL OR state.task_id IS NULL
        ORDER BY task.task_id
        LIMIT 1
        """
    ).fetchone()
    if missing_authority is not None:
        raise RuntimeError(
            "agentic_researcher migration 036 refuses to drop tasks.status before "
            f"Conversation authority is complete: {missing_authority[0]}"
        )

    conn.execute("DROP INDEX IF EXISTS idx_tasks_status")
    conn.execute("DROP INDEX IF EXISTS idx_tasks_project_status")
    conn.execute("DROP INDEX IF EXISTS idx_tasks_project_lifecycle")
    conn.execute("ALTER TABLE tasks DROP COLUMN status")
    conn.execute(
        """
        CREATE INDEX idx_tasks_project_lifecycle
        ON tasks(project_id, archived_at, updated_at, task_id)
        """
    )


@registry.register("literature")
def migration_008_retire_unused_literature_task_saga(conn: sqlite3.Connection) -> None:
    """Retire the empty Literature saga artifact left by the original v7 baseline.

    The saga table was superseded by the durable research-task intent, work
    item, and outbox records. A non-empty artifact is treated as an explicit
    migration blocker so no data is silently discarded and the schema version
    remains unchanged.
    """

    non_empty = [
        table_name
        for table_name in _RETIRED_LITERATURE_TABLES
        if _has_table(conn, table_name)
        and conn.execute(f'SELECT 1 FROM "{table_name}" LIMIT 1').fetchone() is not None
    ]
    if non_empty:
        tables = ", ".join(non_empty)
        raise RuntimeError(
            "literature migration 008 refuses to retire non-empty unused tables: " + tables
        )

    for table_name in _RETIRED_LITERATURE_TABLES:
        if _has_table(conn, table_name):
            conn.execute(f'DROP TABLE "{table_name}"')


@registry.register("literature")
def migration_009_harden_literature_api_attempts(conn: sqlite3.Connection) -> None:
    """Add durable lifecycle columns and guards to external-call attempts.

    Version 8 databases already have the table but predate operation identity,
    response evidence, and response boundary timestamps.  ``ALTER TABLE``
    keeps existing rows.  A historical ``succeeded`` row without the new
    evidence is conservatively retained as ``legacy_state=succeeded`` while
    moving its active state to ``unknown``; it must be reconciled explicitly.
    """

    if not _has_table(conn, "literature_api_attempts"):
        raise RuntimeError("literature API attempt table is required by migration 009")

    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(literature_api_attempts)")}
    additions = {
        "operation": "TEXT NOT NULL DEFAULT 'external'",
        "attempt_number": "INTEGER NOT NULL DEFAULT 1",
        "response_received_at": "TEXT",
        "response_persisted_at": "TEXT",
        "response_payload": "TEXT",
        "legacy_state": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE literature_api_attempts ADD COLUMN "{name}" {definition}')

    if _has_table(conn, "literature_source_snapshots"):
        snapshot_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(literature_source_snapshots)")
        }
        snapshot_additions = {
            "attempt_id": "TEXT",
            "status_code": "INTEGER",
            "cache_control": "TEXT",
        }
        for name, definition in snapshot_additions.items():
            if name not in snapshot_columns:
                conn.execute(
                    f'ALTER TABLE literature_source_snapshots ADD COLUMN "{name}" {definition}'
                )

    conn.execute(
        """
        UPDATE literature_api_attempts
        SET state = 'unknown', legacy_state = 'succeeded',
            error_kind = 'legacy_unreconciled',
            error_message = 'Legacy succeeded row lacks response persistence evidence'
        WHERE state = 'succeeded' AND response_persisted_at IS NULL
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS literature_api_attempts_request_idx
            ON literature_api_attempts (request_fingerprint, work_item_id, attempt_number)
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS literature_api_attempts_state_insert_guard
            BEFORE INSERT ON literature_api_attempts
            WHEN NEW.state NOT IN (
                'started', 'response_received', 'response_persisted', 'succeeded',
                'retryable_failure', 'definitive_failure', 'unknown'
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid Literature API attempt state');
            END
        """
    )
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_insert_evidence_guard")
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_insert_evidence_guard
            BEFORE INSERT ON literature_api_attempts
            WHEN NEW.state IN ('response_persisted', 'succeeded')
              AND length(trim(COALESCE(NEW.response_hash, ''))) = 0
              AND length(trim(COALESCE(NEW.response_payload, ''))) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM literature_source_snapshots AS snapshot
                  WHERE snapshot.attempt_id = NEW.attempt_id
                    AND length(snapshot.body) > 0
                    AND length(trim(COALESCE(snapshot.body_hash, ''))) > 0
              )
            BEGIN
                SELECT RAISE(ABORT, 'Literature API attempt lacks durable response evidence');
            END
        """
    )
    # Recreate the guards on every migration invocation so a database created
    # by an earlier implementation cannot retain the unsafe started-to-
    # response_persisted shortcut or permit success without evidence.
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_state_transition_guard")
    conn.execute("DROP TRIGGER IF EXISTS literature_api_attempts_response_evidence_guard")
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_state_transition_guard
            BEFORE UPDATE OF state ON literature_api_attempts
            WHEN OLD.state != NEW.state AND NOT (
                (OLD.state = 'started' AND NEW.state IN (
                    'response_received', 'retryable_failure',
                    'definitive_failure', 'unknown'
                ))
                OR (OLD.state = 'response_received' AND NEW.state IN (
                    'response_persisted', 'retryable_failure',
                    'definitive_failure', 'unknown'
                ))
                OR (OLD.state = 'response_persisted' AND NEW.state IN (
                    'succeeded', 'unknown', 'retryable_failure',
                    'definitive_failure'
                ))
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid Literature API attempt transition');
            END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER literature_api_attempts_response_evidence_guard
            BEFORE UPDATE OF state ON literature_api_attempts
            WHEN NEW.state IN ('response_persisted', 'succeeded')
              AND length(trim(COALESCE(NEW.response_hash, ''))) = 0
              AND length(trim(COALESCE(NEW.response_payload, ''))) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM literature_source_snapshots AS snapshot
                  WHERE snapshot.attempt_id = NEW.attempt_id
                    AND length(snapshot.body) > 0
                    AND length(trim(COALESCE(snapshot.body_hash, ''))) > 0
              )
            BEGIN
                SELECT RAISE(ABORT, 'Literature API attempt lacks durable response evidence');
            END
        """
    )


@registry.register_baseline("agentic_researcher", _BASELINE_VERSIONS["agentic_researcher"])
def agentic_researcher_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "agentic_researcher")


@registry.register_baseline("auth", _BASELINE_VERSIONS["auth"])
def auth_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "auth")


@registry.register_baseline("literature", _BASELINE_VERSIONS["literature"])
def literature_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "literature")


@registry.register_baseline("terminal", _BASELINE_VERSIONS["terminal"])
def terminal_baseline(conn: sqlite3.Connection) -> None:
    _apply_baseline(conn, "terminal")
