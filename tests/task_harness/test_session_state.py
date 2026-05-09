from __future__ import annotations

from pathlib import Path

from ainrf.task_harness.session_state import SessionCheckpoint, SessionStateStore


def test_save_and_load(tmp_path: Path) -> None:
    store = SessionStateStore(tmp_path)
    checkpoint = SessionCheckpoint(
        task_id="t-1",
        session_id="sess-abc",
        cwd="/tmp",
        created_at="2026-05-08T10:00:00",
        turn_count=3,
        total_cost_usd=0.05,
        pending_prompts=["next"],
    )
    store.save(checkpoint)

    loaded = store.load("t-1")
    assert loaded is not None
    assert loaded.session_id == "sess-abc"
    assert loaded.turn_count == 3
    assert loaded.pending_prompts == ["next"]


def test_load_missing(tmp_path: Path) -> None:
    store = SessionStateStore(tmp_path)
    assert store.load("nonexistent") is None
