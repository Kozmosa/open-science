from __future__ import annotations

import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from ainrf.db.backfill_legacy_turn_items import apply, plan, preflight, verify


pytestmark = [pytest.mark.unit]


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _build_target(path: Path, task_ids: list[str]) -> None:
    baseline = (
        files("ainrf.db.baselines").joinpath("agentic_researcher.sql").read_text(encoding="utf-8")
    )
    with _connect(path) as connection:
        connection.executescript(baseline)
        for task_id in task_ids:
            connection.execute(
                "INSERT INTO tasks (task_id, project_id, workspace_id, environment_id, "
                "researcher_type, harness_engine, title, prompt, owner_user_id, "
                "created_at, updated_at) VALUES "
                "(?, 'project-1', 'workspace-1', 'env-1', 'vanilla', 'claude-code', "
                "'legacy task', 'prompt', 'user-1', '2026-07-01T00:00:00+00:00', "
                "'2026-07-01T00:00:00+00:00')",
                (task_id,),
            )
            connection.execute(
                "INSERT INTO conversation_task_authorities (task_id, authority, created_at) "
                "VALUES (?, 'conversation_v3', '2026-08-17T00:00:00+00:00')",
                (task_id,),
            )
            connection.execute(
                "INSERT INTO task_turns (turn_id, task_id, turn_seq, status, retry_of_turn_id, "
                "engine_family, engine_driver, contract_version, accepted_at, started_at, "
                "finished_at, updated_at) VALUES "
                f"('legacy-inferred-turn:{task_id}', ?, 1, 'completed', NULL, 'claude', "
                "'claude-code', 1, '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00', "
                "'2026-07-01T00:01:00+00:00', '2026-07-01T00:01:00+00:00')",
                (task_id,),
            )


def _build_source(path: Path, rows: list[tuple[str, int, str, str, str]]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE task_outputs (
                task_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, seq)
            )
            """
        )
        connection.executemany("INSERT INTO task_outputs VALUES (?, ?, ?, ?, ?)", rows)


def _sample_rows(task_id: str) -> list[tuple[str, int, str, str, str]]:
    return [
        (
            task_id,
            1,
            "message",
            json.dumps({"role": "user", "content": "hello"}),
            "2026-07-01T01:00:00+00:00",
        ),
        (
            task_id,
            2,
            "lifecycle",
            json.dumps({"event_type": "system", "payload": {"subtype": "task_started"}}),
            "2026-07-01T01:00:01+00:00",
        ),
        (task_id, 3, "token", json.dumps({"event_type": "token"}), "2026-07-01T01:00:02+00:00"),
        (task_id, 4, "thinking", json.dumps({"content": "pondering"}), "2026-07-01T01:00:03+00:00"),
        (
            task_id,
            5,
            "tool_call",
            json.dumps({"id": "call-1", "name": "read_file", "arguments": {"path": "a.txt"}}),
            "2026-07-01T01:00:04+00:00",
        ),
        (
            task_id,
            6,
            "tool_result",
            json.dumps({"tool_use_id": "call-1", "content": "file body"}),
            "2026-07-01T01:00:05+00:00",
        ),
        (
            task_id,
            7,
            "lifecycle",
            json.dumps({"event_type": "system", "payload": {"subtype": "thinking_tokens"}}),
            "2026-07-01T01:00:06+00:00",
        ),
        (
            task_id,
            8,
            "message",
            json.dumps({"role": "assistant", "content": "done"}),
            "2026-07-01T01:00:07+00:00",
        ),
        (task_id, 9, "stderr", "claude exited with code 1", "2026-07-01T01:00:08+00:00"),
        (
            task_id,
            10,
            "lifecycle",
            json.dumps(
                {"event_type": "status", "payload": {"status": "succeeded", "exit_code": 0}}
            ),
            "2026-07-01T01:00:09+00:00",
        ),
    ]


def test_plan_maps_kinds_and_suppresses_telemetry(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _build_source(source, _sample_rows("task-1"))
    plan_data = plan(source)
    items = plan_data.items_by_task["task-1"]
    assert [(i.item_type, i.actor) for i in items] == [
        ("user_message", "user"),
        ("system_notice", "system"),
        ("reasoning_summary", "agent"),
        ("tool_call", "tool"),
        ("tool_result", "tool"),
        ("agent_message", "agent"),
        ("system_notice", "system"),
    ]
    assert (
        plan_data.skipped_output_count == 3
    )  # token + suppressed thinking_tokens + status envelope
    assert items[0].payload == {"text": "hello"}
    assert items[4].call_source_seq == items[3].source_seq
    assert items[6].payload == {"text": "[stderr] claude exited with code 1"}


def test_apply_inserts_items_and_is_rejected_when_rerun(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    (state_root / "runtime").mkdir(parents=True)
    target = state_root / "runtime" / "agentic_researcher.sqlite3"
    source = tmp_path / "source.sqlite3"
    _build_target(target, ["task-1"])
    _build_source(source, _sample_rows("task-1"))

    report = preflight(state_root, source)
    assert report.ready, report.blockers
    assert report.planned_item_count == 7

    applied = apply(state_root, source)
    assert applied.ready, applied.blockers
    assert verify(state_root, source).ready

    with _connect(target) as connection:
        rows = connection.execute(
            "SELECT item_id, item_type, actor, payload_json, task_item_seq, turn_item_seq, "
            "envelope_type, call_item_id, native_provenance_json FROM turn_items "
            "ORDER BY task_item_seq"
        ).fetchall()
        assert len(rows) == 7
        assert [int(r["task_item_seq"]) for r in rows] == list(range(1, 8))
        assert [int(r["turn_item_seq"]) for r in rows] == list(range(1, 8))
        assert json.loads(rows[0]["payload_json"]) == {"text": "hello"}
        assert rows[0]["envelope_type"] == "conversation.item"
        assert rows[1]["envelope_type"] == "canonical_item"
        assert rows[4]["call_item_id"] == rows[3]["item_id"]
        provenance = json.loads(rows[0]["native_provenance_json"])
        assert provenance == {"source": "legacy_task_outputs", "seq": 1, "task_id": "task-1"}

    rerun = preflight(state_root, source)
    assert not rerun.ready
    assert any("already have Items" in blocker for blocker in rerun.blockers)


def test_preflight_blocks_on_task_set_mismatch_and_reverse_mismatch(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    (state_root / "runtime").mkdir(parents=True)
    target = state_root / "runtime" / "agentic_researcher.sqlite3"
    source = tmp_path / "source.sqlite3"
    _build_target(target, ["task-1", "task-2"])
    _build_source(source, _sample_rows("task-1"))

    report = preflight(state_root, source)
    assert not report.ready
    assert any("legacy Turns without source outputs" in blocker for blocker in report.blockers)


def test_plan_fails_closed_on_unmatched_tool_result(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    rows = [
        (
            "task-1",
            1,
            "message",
            json.dumps({"role": "user", "content": "hi"}),
            "2026-07-01T01:00:00+00:00",
        ),
        (
            "task-1",
            2,
            "tool_result",
            json.dumps({"tool_use_id": "call-9", "content": "orphan"}),
            "2026-07-01T01:00:01+00:00",
        ),
    ]
    _build_source(source, rows)
    with pytest.raises(RuntimeError, match="without an earlier unmatched tool_call"):
        plan(source)
