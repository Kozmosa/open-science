"""Standalone Conversation v3 migration contract tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import cast
from collections.abc import Mapping

import pytest

from ainrf.db import connect, run_pending
from ainrf.domain_migration.conversation_v3 import ConversationV3Migration

pytestmark = [pytest.mark.unit]


def _legacy_source(state_root: Path, *, runtime_status: str | None = None) -> Path:
    source = state_root / "runtime" / "agentic_researcher.sqlite3"
    source.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(source)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type,
                harness_engine, status, title, prompt, created_at, updated_at,
                owner_user_id, api_key
            ) VALUES (
                'legacy-task', 'project-legacy', 'workspace-legacy', 'environment-legacy',
                'general', 'codex-app-server', 'succeeded', 'Legacy', 'prompt',
                '2026-07-01T00:00:00+00:00', '2026-07-01T00:05:00+00:00',
                'user-1', 'top-secret-value'
            )"""
        )
        conn.execute(
            """INSERT INTO agent_task_attempts (
                attempt_id, task_id, attempt_seq, trigger, status, created_at,
                started_at, finished_at
            ) VALUES (
                'legacy-attempt', 'legacy-task', 1, 'initial', 'succeeded',
                '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:01+00:00',
                '2026-07-01T00:05:00+00:00'
            )"""
        )
        conn.execute(
            """INSERT INTO task_outputs(task_id, seq, kind, content, created_at)
            VALUES ('legacy-task', 1, 'message', 'safe transcript',
                    '2026-07-01T00:01:00+00:00')"""
        )
        if runtime_status is not None:
            conn.execute(
                """INSERT INTO agent_runtime_sessions(
                    runtime_session_id, attempt_id, launch_key, status, created_at
                ) VALUES ('legacy-runtime', 'legacy-attempt', 'launch-1', ?,
                          '2026-07-01T00:00:01+00:00')""",
                (runtime_status,),
            )
        conn.commit()
    return source


def test_execute_verify_and_cutover_are_deterministic_and_secret_safe(
    state_root: Path, tmp_path: Path
) -> None:
    source = _legacy_source(state_root)
    destination = tmp_path / "conversation-generation.sqlite3"
    pointer = tmp_path / "active-generation.json"
    migration = ConversationV3Migration()

    dry_run = migration.dry_run(source)
    source_hash = str(cast(Mapping[str, object], dry_run["manifest"])["source_sha256"])
    result = migration.execute(source, destination, artifact_sha="artifact-1")
    verification = migration.verify(source, destination)
    cutover = migration.cutover(source, destination, pointer)

    assert cast(Mapping[str, object], result["manifest"])["source_sha256"] == source_hash
    assert verification["ready"] is True
    assert cutover["active_generation"] == str(destination.resolve())
    assert "top-secret-value" not in destination.with_suffix(
        destination.suffix + ".conversation-v3.json"
    ).read_text(encoding="utf-8")
    assert "top-secret-value" not in pointer.read_text(encoding="utf-8")
    assert source.read_bytes().find(b"top-secret-value") >= 0
    assert destination.read_bytes().find(b"top-secret-value") < 0
    with closing(connect(destination)) as conn:
        assert conn.execute(
            "SELECT authority FROM conversation_task_authorities "
            "WHERE task_id = 'legacy-task'"
        ).fetchone()[0] == "conversation_v3"
        assert conn.execute("SELECT COUNT(*) FROM task_turns").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM turn_items").fetchone()[0] == 1


def test_active_or_unknown_legacy_runtime_blocks_execute(
    state_root: Path, tmp_path: Path
) -> None:
    source = _legacy_source(state_root, runtime_status="running")
    migration = ConversationV3Migration()

    assert migration.inspect(source)["ready"] is False
    with pytest.raises(ValueError, match="active or unknown"):
        migration.execute(source, tmp_path / "blocked.sqlite3", artifact_sha="artifact-1")
