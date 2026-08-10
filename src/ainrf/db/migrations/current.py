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
