"""Fresh-install schema baselines for the current product shape."""

from __future__ import annotations

from importlib.resources import files
import sqlite3

from ainrf.db.migration import registry


_BASELINE_VERSIONS = {
    "agentic_researcher": 33,
    "auth": 7,
    "literature": 7,
    "terminal": 1,
}


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
