"""One-time backfill of legacy ``task_outputs`` into canonical Turn Items.

The 2026-08-17 legacy-empty Task migration created one legacy-inferred Turn
per historical Task without Items, which left every pre-cutover Task with an
empty transcript in the WebUI.  This module materializes the retired
``task_outputs`` event stream from a pre-retirement database snapshot into
``turn_items`` rows on those Turns, using the same kind-to-Item mapping the
legacy UI rendered.  The operator runs it during a maintenance window after a
verified backup; normal service startup never imports this module.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

LEGACY_TURN_ID_PREFIX = "legacy-inferred-turn:"
_ENVELOPE_CONVERSATION_ITEM = "conversation.item"
_ENVELOPE_CANONICAL_ITEM = "canonical_item"
# The legacy UI suppressed these lifecycle subtypes, so they are not part of
# the transcript users saw and are not migrated.
_SUPPRESSED_LIFECYCLE_SUBTYPES = frozenset({"status", "thinking_tokens"})
# Pure telemetry events the legacy UI never rendered as transcript rows.
_SKIPPED_KINDS = frozenset({"token"})
_KNOWN_KINDS = (
    frozenset({"message", "thinking", "tool_call", "tool_result", "lifecycle", "stderr", "error"})
    | _SKIPPED_KINDS
)


@dataclass(frozen=True, slots=True)
class PlannedItem:
    """One mapped turn_items row before item ids and sequence numbers exist."""

    source_seq: int
    item_type: str
    actor: str
    payload: dict[str, object]
    occurred_at: str | None
    call_source_seq: int | None = None


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    items_by_task: dict[str, list[PlannedItem]]
    skipped_output_count: int


@dataclass(frozen=True, slots=True)
class BackfillReport:
    ready: bool
    legacy_task_count: int
    planned_task_count: int
    planned_item_count: int
    skipped_output_count: int
    blockers: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _parse_payload(content: str) -> dict[str, object]:
    """Mirror the legacy UI payload parsing: unwrap event envelopes, keep raw text."""

    try:
        parsed: object = json.loads(content)
    except (TypeError, ValueError):
        return {"content": content}
    if not isinstance(parsed, dict):
        return {"content": content}
    wrapped = parsed.get("payload")
    if isinstance(parsed.get("event_type"), str) and isinstance(wrapped, dict):
        return wrapped
    return parsed


def _text_of(payload: dict[str, object], raw: str) -> str:
    value = payload.get("content")
    if isinstance(value, str):
        return value
    if value is None:
        return raw
    return _canonical_json(value)


def _is_status_envelope(raw: str) -> bool:
    """Detect status telemetry wrapped as an event envelope without a subtype."""

    try:
        outer: object = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(outer, dict) and outer.get("event_type") == "status"


def _map_output(kind: str, raw: str) -> PlannedItem | None:
    if kind in _SKIPPED_KINDS:
        return None
    payload = _parse_payload(raw)

    if kind == "message":
        is_user = payload.get("role") == "user"
        return PlannedItem(
            source_seq=0,
            item_type="user_message" if is_user else "agent_message",
            actor="user" if is_user else "agent",
            payload={"text": _text_of(payload, raw)},
            occurred_at=None,
        )
    if kind == "thinking":
        return PlannedItem(
            source_seq=0,
            item_type="reasoning_summary",
            actor="agent",
            payload={"text": _text_of(payload, raw)},
            occurred_at=None,
        )
    if kind == "tool_call":
        return PlannedItem(
            source_seq=0,
            item_type="tool_call",
            actor="tool",
            payload={key: payload[key] for key in ("id", "name", "arguments") if key in payload},
            occurred_at=None,
        )
    if kind == "tool_result":
        return PlannedItem(
            source_seq=0,
            item_type="tool_result",
            actor="tool",
            payload={key: payload[key] for key in ("tool_use_id", "content") if key in payload},
            occurred_at=None,
        )
    if kind == "lifecycle":
        subtype = payload.get("subtype")
        if isinstance(subtype, str) and subtype in _SUPPRESSED_LIFECYCLE_SUBTYPES:
            return None
        if not (isinstance(subtype, str) and subtype) and _is_status_envelope(raw):
            return None
        text = subtype if isinstance(subtype, str) and subtype else _text_of(payload, raw)
        return PlannedItem(
            source_seq=0,
            item_type="system_notice",
            actor="system",
            payload={"text": text},
            occurred_at=None,
        )
    if kind == "stderr":
        return PlannedItem(
            source_seq=0,
            item_type="system_notice",
            actor="system",
            payload={"text": f"[stderr] {_text_of(payload, raw)}"},
            occurred_at=None,
        )
    if kind == "error":
        return PlannedItem(
            source_seq=0,
            item_type="error",
            actor="system",
            payload={"text": _text_of(payload, raw)},
            occurred_at=None,
        )
    raise RuntimeError(f"task_outputs row has unknown kind {kind!r}")


def _plan_task(rows: list[sqlite3.Row]) -> tuple[list[PlannedItem], int]:
    planned: list[PlannedItem] = []
    pending_call_seqs: list[int] = []
    skipped = 0
    for row in rows:
        mapped = _map_output(str(row["kind"]), str(row["content"]))
        if mapped is None:
            skipped += 1
            continue
        item = PlannedItem(
            source_seq=int(row["seq"]),
            item_type=mapped.item_type,
            actor=mapped.actor,
            payload=mapped.payload,
            occurred_at=str(row["created_at"]),
        )
        if mapped.item_type == "tool_call":
            pending_call_seqs.append(item.source_seq)
        elif mapped.item_type == "tool_result":
            if not pending_call_seqs:
                raise RuntimeError(
                    f"task {row['task_id']} output seq {item.source_seq} is a tool_result "
                    "without an earlier unmatched tool_call"
                )
            item = PlannedItem(
                source_seq=item.source_seq,
                item_type=item.item_type,
                actor=item.actor,
                payload=item.payload,
                occurred_at=item.occurred_at,
                call_source_seq=pending_call_seqs.pop(0),
            )
        planned.append(item)
    return planned, skipped


def plan(legacy_source_db: Path) -> MigrationPlan:
    """Map every source task_outputs row to planned Items, keyed by task id."""

    with _connect_source(legacy_source_db) as source:
        tables = {
            str(row[0])
            for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "task_outputs" not in tables:
            raise RuntimeError(
                f"{legacy_source_db} has no task_outputs table; provide a pre-retirement snapshot"
            )
        items_by_task: dict[str, list[PlannedItem]] = {}
        skipped_total = 0
        unknown_kinds = {
            str(row[0]) for row in source.execute("SELECT DISTINCT kind FROM task_outputs")
        } - _KNOWN_KINDS
        if unknown_kinds:
            raise RuntimeError(f"source has unknown task_outputs kinds: {sorted(unknown_kinds)}")
        for task_row in source.execute(
            "SELECT DISTINCT task_id FROM task_outputs ORDER BY task_id"
        ):
            task_id = str(task_row["task_id"])
            items, skipped = _plan_task(
                list(
                    source.execute(
                        "SELECT task_id, seq, kind, content, created_at FROM task_outputs "
                        "WHERE task_id = ? ORDER BY seq",
                        (task_id,),
                    )
                )
            )
            items_by_task[task_id] = items
            skipped_total += skipped
        return MigrationPlan(items_by_task=items_by_task, skipped_output_count=skipped_total)


def _connect_source(legacy_source_db: Path) -> sqlite3.Connection:
    if not legacy_source_db.is_file():
        raise FileNotFoundError(f"legacy source database not found: {legacy_source_db}")
    connection = sqlite3.connect(f"file:{legacy_source_db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _database_path(state_root: Path) -> Path:
    return state_root / "runtime" / "agentic_researcher.sqlite3"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _legacy_turns(conn: sqlite3.Connection) -> dict[str, str]:
    """Return task_id -> turn_id for the legacy-inferred Turns."""

    turns: dict[str, str] = {}
    for row in conn.execute(
        "SELECT task_id, turn_id, turn_seq FROM task_turns WHERE turn_id LIKE ?",
        (f"{LEGACY_TURN_ID_PREFIX}%",),
    ):
        expected = f"{LEGACY_TURN_ID_PREFIX}{row['task_id']}"
        if str(row["turn_id"]) != expected or int(row["turn_seq"]) != 1:
            raise RuntimeError(
                f"unexpected legacy Turn {row['turn_id']!r} for task {row['task_id']!r}"
            )
        turns[str(row["task_id"])] = str(row["turn_id"])
    return turns


def _report(
    plan_data: MigrationPlan, blockers: list[str], legacy_task_count: int
) -> BackfillReport:
    return BackfillReport(
        ready=not blockers,
        legacy_task_count=legacy_task_count,
        planned_task_count=len(plan_data.items_by_task),
        planned_item_count=sum(len(items) for items in plan_data.items_by_task.values()),
        skipped_output_count=plan_data.skipped_output_count,
        blockers=tuple(blockers),
    )


def preflight(state_root: Path, legacy_source_db: Path) -> BackfillReport:
    """Report read-only whether the backfill is safe to apply to this state root."""

    plan_data = plan(legacy_source_db)
    blockers: list[str] = []
    with _connect_read_only(_database_path(state_root)) as conn:
        try:
            turns = _legacy_turns(conn)
        except RuntimeError as exc:
            blockers.append(str(exc))
            turns = {}
        if not turns:
            blockers.append("no legacy-inferred Turns found in the target database")
        if turns:
            placeholders = ",".join("?" for _ in turns)
            tasks_with_items = [
                str(row["task_id"])
                for row in conn.execute(
                    f"SELECT DISTINCT task_id FROM turn_items WHERE task_id IN ({placeholders})",
                    tuple(turns),
                )
            ]
            if tasks_with_items:
                blockers.append(
                    "tasks already have Items, backfill would not be idempotent: "
                    + ", ".join(sorted(tasks_with_items)[:5])
                )
    source_only = sorted(set(plan_data.items_by_task) - set(turns))
    target_only = sorted(set(turns) - set(plan_data.items_by_task))
    if source_only:
        blockers.append(f"source tasks without a legacy Turn: {', '.join(source_only[:5])}")
    if target_only:
        blockers.append(f"legacy Turns without source outputs: {', '.join(target_only[:5])}")
    empty_tasks = sorted(task_id for task_id, items in plan_data.items_by_task.items() if not items)
    if empty_tasks:
        blockers.append(f"source tasks with no migratable outputs: {', '.join(empty_tasks[:5])}")
    return _report(plan_data, blockers, len(turns))


def apply(state_root: Path, legacy_source_db: Path) -> BackfillReport:
    """Insert the planned Items on the legacy-inferred Turns in one transaction."""

    plan_data = plan(legacy_source_db)
    report = preflight(state_root, legacy_source_db)
    if not report.ready:
        return report
    ingested_at = _now()
    with sqlite3.connect(_database_path(state_root)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            turns = _legacy_turns(conn)
            placeholders = ",".join("?" for _ in turns)
            tasks_with_items = {
                str(row["task_id"])
                for row in conn.execute(
                    f"SELECT DISTINCT task_id FROM turn_items WHERE task_id IN ({placeholders})",
                    tuple(turns),
                )
            }
            if tasks_with_items or set(turns) != set(plan_data.items_by_task):
                raise RuntimeError("target database changed since preflight; rerun preflight")
            item_id_by_source_seq: dict[tuple[str, int], str] = {}
            for task_id in sorted(plan_data.items_by_task):
                turn_id = turns[task_id]
                for seq, item in enumerate(plan_data.items_by_task[task_id], start=1):
                    item_id = uuid4().hex
                    item_id_by_source_seq[(task_id, item.source_seq)] = item_id
                    call_item_id = (
                        item_id_by_source_seq[(task_id, item.call_source_seq)]
                        if item.call_source_seq is not None
                        else None
                    )
                    conn.execute(
                        """
                        INSERT INTO turn_items (
                            item_id, task_id, turn_id, task_item_seq, turn_item_seq,
                            envelope_type, envelope_version, item_type, actor,
                            payload_json, native_provenance_json,
                            native_dedupe_scope, native_item_id,
                            parent_item_id, call_item_id,
                            occurred_at, ingested_at, persisted_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?
                        )
                        """,
                        (
                            item_id,
                            task_id,
                            turn_id,
                            seq,
                            seq,
                            _ENVELOPE_CONVERSATION_ITEM
                            if item.item_type == "user_message"
                            else _ENVELOPE_CANONICAL_ITEM,
                            item.item_type,
                            item.actor,
                            _canonical_json(item.payload),
                            _canonical_json(
                                {
                                    "source": "legacy_task_outputs",
                                    "task_id": task_id,
                                    "seq": item.source_seq,
                                }
                            ),
                            call_item_id,
                            item.occurred_at,
                            ingested_at,
                            ingested_at,
                        ),
                    )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return verify(state_root, legacy_source_db)


def verify(state_root: Path, legacy_source_db: Path) -> BackfillReport:
    """Check that every planned Item now exists on its legacy-inferred Turn."""

    plan_data = plan(legacy_source_db)
    blockers: list[str] = []
    with _connect_read_only(_database_path(state_root)) as conn:
        turns = _legacy_turns(conn)
        for task_id, planned in sorted(plan_data.items_by_task.items()):
            turn_id = turns.get(task_id)
            if turn_id is None:
                blockers.append(f"task {task_id} lost its legacy Turn")
                continue
            actual = int(
                conn.execute(
                    "SELECT COUNT(*) FROM turn_items WHERE turn_id = ? AND task_id = ?",
                    (turn_id, task_id),
                ).fetchone()[0]
            )
            if actual != len(planned):
                blockers.append(f"task {task_id} has {actual} Items, expected {len(planned)}")
        if conn.execute("PRAGMA foreign_key_check(turn_items)").fetchone() is not None:
            blockers.append("turn_items foreign key check reported violations")
    return _report(plan_data, blockers, len(turns))
