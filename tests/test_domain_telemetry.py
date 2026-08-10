"""Durable domain telemetry and release-alert baseline tests."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

import pytest
import structlog
import yaml

import ainrf.domain_telemetry as domain_telemetry
from ainrf.telemetry.metrics import get_metrics_text, reset_metrics
from ainrf.db import connect, run_pending
from ainrf.domain import build_domain_modules
from ainrf.domain.service import DomainConflictError
from ainrf.domain_telemetry import record_idempotency_event, refresh_domain_metrics


pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_metrics() -> Iterator[None]:
    reset_metrics()
    yield
    reset_metrics()


def _timestamp(*, minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _sqlite_source_digest(paths: tuple[Path, ...]) -> dict[str, str]:
    members = (
        member
        for path in paths
        for member in (
            path,
            path.with_name(f"{path.name}-wal"),
            path.with_name(f"{path.name}-shm"),
        )
        if member.is_file()
    )
    return {str(member): hashlib.sha256(member.read_bytes()).hexdigest() for member in members}


def _seed_control_plane(state_root: Path) -> None:
    """Create migrated durable stores with one representative control-plane fact."""

    runtime_root = state_root / "runtime"
    runtime_root.mkdir(parents=True)
    control_path = runtime_root / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        run_pending(conn, "agentic_researcher")
        conn.execute(
            """
            INSERT INTO domain_idempotency_requests (
                actor_user_id, scope, idempotency_key, request_hash, response_json, created_at
            ) VALUES ('telemetry-user', 'task.create', 'telemetry-key', 'hash', '{}', ?)
            """,
            (_timestamp(minutes_ago=20),),
        )
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type, harness_engine,
                title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('telemetry-task', 'telemetry-project', 'telemetry-workspace',
                      'telemetry-environment', 'general', 'codex-app-server', 'Telemetry',
                      'collect telemetry', ?, ?, 'telemetry-user')
            """,
            (_timestamp(minutes_ago=12), _timestamp(minutes_ago=12)),
        )
        conn.execute(
            """
            INSERT INTO conversation_task_authorities (task_id, authority, created_at)
            VALUES ('telemetry-task', 'conversation_v3', ?)
            """,
            (_timestamp(minutes_ago=12),),
        )
        conn.execute(
            """
            INSERT INTO turn_submissions (
                submission_id, task_id, reserved_turn_id, actor_user_id,
                idempotency_key, request_hash, status, input_json, created_at, updated_at
            ) VALUES ('telemetry-submission', 'telemetry-task', 'telemetry-turn',
                      'telemetry-user', 'telemetry-submission-key', 'submission-hash',
                      'queued', '{"text":"collect telemetry"}', ?, ?)
            """,
            (_timestamp(minutes_ago=12), _timestamp(minutes_ago=12)),
        )
        conn.execute(
            """
            INSERT INTO overview_snapshots (
                snapshot_id, owner_user_id, snapshot_date, payload_json, created_at
            ) VALUES ('telemetry-snapshot', 'telemetry-user', '2026-07-13', '{}', ?)
            """,
            (_timestamp(minutes_ago=6),),
        )
        conn.execute(
            """
            INSERT INTO overview_refresh_jobs (
                job_id, owner_user_id, trigger, scheduled_for_date, status, created_at, updated_at
            ) VALUES ('telemetry-overview-job', 'telemetry-user', 'scheduled', '2026-07-13',
                      'queued', ?, ?)
            """,
            (_timestamp(minutes_ago=5), _timestamp(minutes_ago=5)),
        )
        conn.commit()

    auth_path = runtime_root / "auth.sqlite3"
    with closing(connect(auth_path)) as conn:
        run_pending(conn, "auth")
        conn.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, role, status, created_at
            ) VALUES ('telemetry-user', 'telemetry-user', 'not-used', 'Telemetry User',
                      'member', 'active', ?)
            """,
            (_timestamp(minutes_ago=30),),
        )
        conn.commit()

    literature_path = runtime_root / "literature.sqlite3"
    with closing(connect(literature_path)) as conn:
        run_pending(conn, "literature")
        conn.execute(
            """
            INSERT INTO literature_work_items (
                work_item_id, kind, idempotency_key, status, payload_json, available_at,
                created_at, updated_at
            ) VALUES ('telemetry-work-item', 'research_task', 'telemetry-work-key', 'pending',
                      '{}', ?, ?, ?)
            """,
            (_timestamp(minutes_ago=18), _timestamp(minutes_ago=18), _timestamp(minutes_ago=18)),
        )
        conn.execute(
            """
            INSERT INTO literature_research_task_intents (
                intent_id, user_id, paper_id, project_id, workspace_id, actor_role, task_preset,
                title, request_input_json, request_hash, idempotency_key, task_idempotency_key,
                status, work_item_id, created_at, updated_at
            ) VALUES ('telemetry-intent', 'telemetry-user', 'paper-telemetry', 'telemetry-project',
                      'telemetry-workspace', 'member', 'research', 'Telemetry research', '{}',
                      'telemetry-request-hash', 'telemetry-intent-key', 'telemetry-task-key',
                      'pending', 'telemetry-work-item', ?, ?)
            """,
            (_timestamp(minutes_ago=18), _timestamp(minutes_ago=18)),
        )
        conn.commit()


def test_refresh_reads_current_durable_control_plane_state(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_oldest_pending_age_seconds >= 11 * 60
    assert snapshot.submission_backlog_count == 1
    assert snapshot.idempotency_record_count == 1
    assert snapshot.literature_pending_age_seconds >= 17 * 60
    assert snapshot.overview_oldest_age_seconds >= 5 * 60
    assert snapshot.overview_missing_active_user_count == 0

    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 1.0" in text
    assert 'ainrf_domain_telemetry_source_status{source="control",state="ready"} 1.0' in text
    assert "ainrf_domain_turn_submission_oldest_pending_age_seconds" in text
    assert 'ainrf_domain_literature_saga_intents{status="pending"} 1.0' in text
    assert 'ainrf_domain_overview_refresh_jobs{status="queued"} 1.0' in text


def test_active_maintenance_telemetry_scrape_does_not_initialize_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        conn.execute("UPDATE domain_maintenance_state SET is_active = 1 WHERE singleton = 1")
        conn.commit()

    def _unexpected_persist(
        _state_root: Path,
        _collected: domain_telemetry._CollectedDomainMetrics,
        *,
        collected_at: float,
    ) -> None:
        _ = collected_at
        raise AssertionError("maintenance telemetry must not persist a snapshot")

    monkeypatch.setattr(domain_telemetry, "_persist_collected_snapshot", _unexpected_persist)
    sources = (
        control_path,
        tmp_path / "runtime" / "auth.sqlite3",
        tmp_path / "runtime" / "literature.sqlite3",
    )
    before = _sqlite_source_digest(sources)
    snapshot = refresh_domain_metrics(tmp_path, read_only=True)

    assert snapshot.submission_backlog_count == 1
    assert _sqlite_source_digest(sources) == before


def test_read_only_telemetry_defers_a_wal_source_without_changing_it(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    wal_path = control_path.with_name(f"{control_path.name}-wal")
    wal_path.write_bytes(b"maintenance-wal-marker")
    sources = (
        control_path,
        tmp_path / "runtime" / "auth.sqlite3",
        tmp_path / "runtime" / "literature.sqlite3",
    )
    before = _sqlite_source_digest(sources)

    snapshot = refresh_domain_metrics(tmp_path, read_only=True)

    assert snapshot.submission_backlog_count == 0
    assert _sqlite_source_digest(sources) == before
    text = get_metrics_text()
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert 'ainrf_domain_telemetry_source_status{source="control",state="unavailable"} 1.0' in text


def test_read_only_telemetry_failure_never_records_a_durable_sqlite_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)

    def _raise_locked(_path: Path, *, source: str) -> sqlite3.Connection:
        _ = source
        raise sqlite3.OperationalError("database is locked")

    def _unexpected_sqlite_error(**_kwargs: object) -> None:
        raise AssertionError("read-only telemetry must not write a durable error counter")

    monkeypatch.setattr(domain_telemetry, "_maintenance_read_only", _raise_locked)
    monkeypatch.setattr(domain_telemetry, "record_sqlite_error", _unexpected_sqlite_error)

    snapshot = refresh_domain_metrics(tmp_path, read_only=True)

    assert snapshot.submission_backlog_count == 0
    assert "ainrf_domain_metrics_risk_state_known 0.0" in get_metrics_text()


@pytest.mark.parametrize(
    ("source", "expected_state"),
    (
        ("auth", "missing"),
        ("literature", "missing"),
        ("control", "schema_invalid"),
        ("overview", "schema_invalid"),
    ),
)
def test_current_missing_required_telemetry_source_fails_closed(
    tmp_path: Path,
    source: str,
    expected_state: str,
) -> None:
    _seed_control_plane(tmp_path)
    runtime_root = tmp_path / "runtime"
    control_path = runtime_root / "agentic_researcher.sqlite3"
    if source == "auth":
        (runtime_root / "auth.sqlite3").unlink()
    elif source == "literature":
        (runtime_root / "literature.sqlite3").unlink()
    elif source == "control":
        with closing(sqlite3.connect(control_path)) as conn:
            conn.execute("DROP TABLE turn_submissions")
            conn.commit()
    else:
        with closing(sqlite3.connect(control_path)) as conn:
            conn.execute("DROP TABLE overview_snapshots")
            conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 0
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert "ainrf_domain_turn_submission_backlog NaN" in text
    assert (
        f'ainrf_domain_telemetry_source_status{{source="{source}",state="{expected_state}"}} 1.0'
        in text
    )


def test_current_source_readiness_failure_never_reuses_cached_risk_gauges(
    tmp_path: Path,
) -> None:
    _seed_control_plane(tmp_path)
    expected = refresh_domain_metrics(tmp_path)
    assert expected.submission_backlog_count == 1
    (tmp_path / "runtime" / "auth.sqlite3").unlink()

    actual = refresh_domain_metrics(tmp_path)

    assert actual.submission_backlog_count == 0
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert "ainrf_domain_turn_submission_backlog NaN" in text
    assert 'ainrf_domain_telemetry_source_status{source="auth",state="missing"} 1.0' in text


def test_unavailable_control_source_retains_cached_risk_with_red_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    expected = refresh_domain_metrics(tmp_path)
    assert expected.submission_backlog_count == 1
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    original_read_only = domain_telemetry._read_only

    def _raise_control_locked(path: Path) -> sqlite3.Connection:
        if path == control_path:
            raise sqlite3.OperationalError("database is locked")
        return original_read_only(path)

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_control_locked)

    actual = refresh_domain_metrics(tmp_path)

    assert actual == expected
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 1.0" in text
    assert "ainrf_domain_turn_submission_backlog 1.0" in text
    assert 'ainrf_domain_telemetry_source_status{source="control",state="unavailable"} 1.0' in text


def test_unavailable_external_source_retains_cached_risk_with_red_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    expected = refresh_domain_metrics(tmp_path)
    assert expected.submission_backlog_count == 1
    auth_path = tmp_path / "runtime" / "auth.sqlite3"
    original_read_only = domain_telemetry._read_only

    def _raise_auth_locked(path: Path) -> sqlite3.Connection:
        if path == auth_path:
            raise sqlite3.OperationalError("database is locked")
        return original_read_only(path)

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_auth_locked)

    actual = refresh_domain_metrics(tmp_path)

    assert actual == expected
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 1.0" in text
    assert "ainrf_domain_turn_submission_backlog 1.0" in text
    assert 'ainrf_domain_telemetry_source_status{source="auth",state="unavailable"} 1.0' in text


def test_current_schema_readiness_rejects_an_old_auth_source(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    auth_path = tmp_path / "runtime" / "auth.sqlite3"
    with closing(sqlite3.connect(auth_path)) as conn:
        conn.execute("UPDATE _schema_version SET version = 1 WHERE database = 'auth'")
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 0
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert 'ainrf_domain_telemetry_source_status{source="auth",state="schema_invalid"} 1.0' in text


def test_current_control_source_rejects_pre_retirement_schema(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(sqlite3.connect(control_path)) as conn:
        conn.execute(
            "UPDATE _schema_version SET version = 32 WHERE database = 'agentic_researcher'"
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 0
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert (
        'ainrf_domain_telemetry_source_status{source="control",state="schema_invalid"} 1.0' in text
    )


def test_overview_attention_survives_a_fresh_partial_snapshot(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    now = _timestamp()
    with closing(connect(control_path)) as conn:
        conn.execute(
            """
            UPDATE overview_snapshots
            SET created_at = ?, data_cutoff_at = ?, source_status = 'partial', attention_required = 1
            WHERE snapshot_id = 'telemetry-snapshot'
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO overview_refresh_card_states (
                owner_user_id, card_id, last_job_id, status, data_json, data_cutoff_at, updated_at
            ) VALUES ('telemetry-user', 'literature', 'telemetry-overview-job', 'stale', '{}', ?, ?)
            """,
            (_timestamp(minutes_ago=30), now),
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.overview_oldest_age_seconds < 5.0
    assert snapshot.overview_attention_required_count == 1
    text = get_metrics_text()
    assert 'ainrf_domain_overview_card_states{status="stale"} 1.0' in text
    assert "ainrf_domain_overview_attention_required 1.0" in text


@pytest.mark.parametrize(
    "created_at",
    (
        "not-a-timestamp",
        "2099-01-01T00:00:00+00:00",
    ),
)
def test_overview_untrusted_snapshot_timestamp_is_stale_and_requires_attention(
    tmp_path: Path, created_at: str
) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        conn.execute(
            """
            UPDATE overview_snapshots
            SET created_at = ?, source_status = 'ok', attention_required = 0
            WHERE snapshot_id = 'telemetry-snapshot'
            """,
            (created_at,),
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.overview_oldest_age_seconds > 30 * 60 * 60
    assert snapshot.overview_attention_required_count == 1
    text = get_metrics_text()
    assert "ainrf_domain_overview_attention_required 1.0" in text


def test_truncated_persisted_snapshot_never_becomes_a_known_risk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    refresh_domain_metrics(tmp_path)
    sidecar = tmp_path / "runtime" / "domain_telemetry.sqlite3"
    with closing(sqlite3.connect(sidecar)) as conn:
        row = conn.execute(
            "SELECT payload_json FROM domain_telemetry_snapshots WHERE singleton = 1"
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        payload["submission_backlog"].pop()
        conn.execute(
            "UPDATE domain_telemetry_snapshots SET payload_json = ? WHERE singleton = 1",
            (json.dumps(payload),),
        )
        conn.commit()

    domain_telemetry._LAST_GOOD_SCRAPES.clear()
    domain_telemetry._LAST_SUCCESS_TIMESTAMPS.clear()
    reset_metrics()

    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    original_read_only = domain_telemetry._read_only

    def _raise_locked(path: Path) -> sqlite3.Connection:
        if path == control_path:
            raise sqlite3.OperationalError("database is locked")
        return original_read_only(path)

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_locked)
    refresh_domain_metrics(tmp_path)

    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert "ainrf_domain_turn_submission_backlog NaN" in text


def test_duplicate_persisted_dynamic_counter_is_rejected(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    domain_telemetry.record_idempotency_event("accepted", state_root=tmp_path)
    refresh_domain_metrics(tmp_path)
    sidecar = tmp_path / "runtime" / "domain_telemetry.sqlite3"
    with closing(sqlite3.connect(sidecar)) as conn:
        row = conn.execute(
            "SELECT payload_json FROM domain_telemetry_snapshots WHERE singleton = 1"
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row[0]))
    counter = next(
        item
        for item in payload["durable_counters"]
        if item["metric_name"] == "ainrf_domain_idempotency_requests_total"
    )
    payload["durable_counters"].append(counter)

    with pytest.raises(domain_telemetry._TelemetryStoreError):
        domain_telemetry._snapshot_from_payload(json.dumps(payload))


def test_idempotency_telemetry_redacts_raw_key_from_structured_logs() -> None:
    raw_key = "super-secret-idempotency-key"

    with structlog.testing.capture_logs() as logs:
        record_idempotency_event(
            "accepted",
            scope="task.create",
            idempotency_key=raw_key,
            user_id="telemetry-user",
        )

    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == "domain_idempotency"
    assert entry["idempotency_key_fingerprint"] != raw_key
    assert "idempotency_key" not in entry
    assert raw_key not in entry.values()
    assert 'ainrf_domain_idempotency_requests_total{outcome="accepted"} 1.0' in get_metrics_text()


def test_durable_idempotency_logs_only_current_conversation_correlations() -> None:
    request = {
        "task_id": "task-current",
        "attempt_id": "attempt-retired",
        "runtime_session_id": "session-retired",
        "migration_run_id": "migration-retired",
    }
    response = {
        "reserved_turn_id": "turn-current",
        "submission_id": "submission-current",
        "runtime_execution_id": "execution-current",
    }

    with structlog.testing.capture_logs() as logs:
        domain_telemetry.record_durable_idempotency_event(
            "reused",
            actor_user_id="telemetry-user",
            scope="task.turn.retry",
            idempotency_key="current-key",
            request=request,
            response=response,
        )

    entry = logs[0]
    assert entry["task_id"] == "task-current"
    assert entry["turn_id"] == "turn-current"
    assert entry["submission_id"] == "submission-current"
    assert entry["runtime_execution_id"] == "execution-current"
    assert "attempt_id" not in entry
    assert "runtime_session_id" not in entry
    assert "run_id" not in entry


def test_redaction_handles_camel_case_secrets_and_unknown_details() -> None:
    with structlog.testing.capture_logs() as logs:
        domain_telemetry.log_domain_event(
            "domain_test_redaction",
            accessToken="access-token-value",
            sessionCookie="cookie-value",
            arbitraryDetail="tenant-private-detail",
            taskId="task-123",
        )

    entry = logs[0]
    assert entry["accessToken"] == "[REDACTED]"
    assert entry["sessionCookie"] == "[REDACTED]"
    assert "arbitraryDetail" not in entry
    assert entry["arbitraryDetail_fingerprint"] != "tenant-private-detail"
    assert entry["taskId"] == "task-123"


def test_failed_scrape_retains_last_known_good_gauges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    expected = refresh_domain_metrics(tmp_path)

    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    original_read_only = domain_telemetry._read_only

    def _raise_locked(path: Path) -> sqlite3.Connection:
        if path == control_path:
            raise sqlite3.OperationalError("database is locked")
        return original_read_only(path)

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_locked)
    actual = refresh_domain_metrics(tmp_path)

    assert actual == expected
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_turn_submission_backlog 1.0" in text
    assert "ainrf_domain_metrics_last_success_timestamp_seconds" in text


def test_no_port_worker_events_are_hydrated_from_the_durable_store(tmp_path: Path) -> None:
    """A fresh API process observes worker/CLI events without shared memory."""

    _seed_control_plane(tmp_path)
    domain_telemetry.record_literature_saga_event(
        "completed",
        user_id="telemetry-user",
        task_id="telemetry-task",
        state_root=tmp_path,
    )
    domain_telemetry.record_overview_event(
        "succeeded",
        trigger="scheduled",
        user_id="telemetry-user",
        job_id="telemetry-overview-job",
        state_root=tmp_path,
    )
    domain_telemetry.record_sqlite_error(
        operation="connection_execute",
        error=sqlite3.OperationalError("database is locked"),
        state_root=tmp_path,
    )

    refresh_domain_metrics(tmp_path)
    text = get_metrics_text()
    assert 'ainrf_domain_literature_saga_events_total{outcome="completed"} 1.0' in text
    assert (
        'ainrf_domain_overview_refresh_events_total{outcome="succeeded",trigger="scheduled"} 1.0'
        in text
    )
    assert (
        'ainrf_domain_sqlite_errors_total{error_type="OperationalError",kind="busy_or_locked",operation="connection_execute"} 1.0'
        in text
    )


def test_restart_uses_persisted_snapshot_when_source_scrape_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    expected = refresh_domain_metrics(tmp_path)

    # Simulate a separate API worker after the first process exited: its
    # process-local cache is empty, while the durable telemetry sidecar stays.
    domain_telemetry._LAST_GOOD_SCRAPES.clear()
    domain_telemetry._LAST_SUCCESS_TIMESTAMPS.clear()
    reset_metrics()

    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    original_read_only = domain_telemetry._read_only

    def _raise_locked(path: Path) -> sqlite3.Connection:
        if path == control_path:
            raise sqlite3.OperationalError("database is locked")
        return original_read_only(path)

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_locked)
    actual = refresh_domain_metrics(tmp_path)

    assert actual == expected
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 1.0" in text
    assert "ainrf_domain_turn_submission_backlog 1.0" in text


def test_uncached_scrape_failure_exports_unknown_risk_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)

    def _raise_locked(_path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(domain_telemetry, "_read_only", _raise_locked)
    refresh_domain_metrics(tmp_path)

    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert "ainrf_domain_turn_submission_backlog NaN" in text


def test_lost_durable_event_latches_release_telemetry_until_operator_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)
    refresh_domain_metrics(tmp_path)
    original_open = domain_telemetry._open_telemetry_store

    def _fail_counter_store(state_root: Path, *, create: bool) -> sqlite3.Connection | None:
        if create:
            raise domain_telemetry._TelemetryStoreError("simulated sidecar write failure")
        return original_open(state_root, create=create)

    monkeypatch.setattr(domain_telemetry, "_open_telemetry_store", _fail_counter_store)
    domain_telemetry.record_idempotency_event("accepted", state_root=tmp_path)
    assert (tmp_path / "runtime" / "domain_telemetry_delivery_failure.json").is_file()

    monkeypatch.setattr(domain_telemetry, "_open_telemetry_store", original_open)
    reset_metrics()
    refresh_domain_metrics(tmp_path)

    assert "ainrf_domain_telemetry_delivery_failure_latched 1.0" in get_metrics_text()


def test_missing_initialized_sidecar_fails_closed_instead_of_resetting_counters(
    tmp_path: Path,
) -> None:
    _seed_control_plane(tmp_path)
    refresh_domain_metrics(tmp_path)
    sidecar = tmp_path / "runtime" / "domain_telemetry.sqlite3"
    assert sidecar.is_file()
    sidecar.unlink()
    domain_telemetry._LAST_GOOD_SCRAPES.clear()
    domain_telemetry._LAST_SUCCESS_TIMESTAMPS.clear()
    reset_metrics()

    refresh_domain_metrics(tmp_path)

    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text
    assert "ainrf_domain_telemetry_delivery_failure_latched 1.0" in text


def test_unexpected_domain_metric_exception_is_exported_as_failed_scrape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_control_plane(tmp_path)

    def _unexpected_submission_metrics(
        conn: sqlite3.Connection, now: datetime
    ) -> tuple[float, dict[str, int]]:
        _ = conn, now
        raise RuntimeError("unexpected telemetry collector failure")

    monkeypatch.setattr(domain_telemetry, "_submission_metrics", _unexpected_submission_metrics)
    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 0
    text = get_metrics_text()
    assert "ainrf_domain_metrics_scrape_success 0.0" in text
    assert "ainrf_domain_metrics_risk_state_known 0.0" in text


def test_telemetry_store_closes_connection_when_its_bootstrap_pragma_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenConnection:
        def __init__(self) -> None:
            self.row_factory: object | None = None
            self.closed = False

        def execute(self, query: str) -> None:
            _ = query
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            self.closed = True

    connection = BrokenConnection()
    monkeypatch.setattr(domain_telemetry.sqlite3, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(domain_telemetry._TelemetryStoreError):
        domain_telemetry._open_telemetry_store(tmp_path, create=True)

    assert connection.closed is True


def test_accepted_running_execution_is_not_counted_as_submission_backlog(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, workspace_id, environment_id, researcher_type, harness_engine,
                title, prompt, created_at, updated_at, owner_user_id
            ) VALUES ('normal-runtime-task', 'telemetry-project', 'telemetry-workspace',
                      'telemetry-environment', 'general', 'codex-app-server',
                      'Normal runtime',
                      'do not alert', ?, ?, 'telemetry-user')
            """,
            (_timestamp(minutes_ago=30), _timestamp()),
        )
        conn.execute(
            """
            INSERT INTO conversation_task_authorities (task_id, authority, created_at)
            VALUES ('normal-runtime-task', 'conversation_v3', ?)
            """,
            (_timestamp(minutes_ago=30),),
        )
        conn.execute(
            """
            INSERT INTO turn_submissions (
                submission_id, task_id, reserved_turn_id, actor_user_id,
                idempotency_key, request_hash, status, input_json,
                native_turn_kind, native_turn_ref, created_at, claimed_at,
                delivering_at, accepted_at, finished_at, updated_at
            ) VALUES ('normal-runtime-submission', 'normal-runtime-task', 'normal-runtime-turn',
                      'telemetry-user', 'normal-runtime-key', 'normal-runtime-hash', 'delivered',
                      '{"text":"run normally"}', 'codex-thread', 'thread-normal', ?, ?, ?, ?, ?, ?)
            """,
            (
                _timestamp(minutes_ago=30),
                _timestamp(minutes_ago=30),
                _timestamp(minutes_ago=30),
                _timestamp(minutes_ago=30),
                _timestamp(minutes_ago=30),
                _timestamp(),
            ),
        )
        conn.execute(
            """
            INSERT INTO task_turns (
                turn_id, task_id, turn_seq, status, engine_family, engine_driver,
                contract_version, native_turn_kind, native_turn_ref,
                accepted_at, started_at, updated_at
            ) VALUES ('normal-runtime-turn', 'normal-runtime-task', 1, 'in_progress',
                      'codex', 'codex-app-server', 1, 'codex-thread', 'thread-normal', ?, ?, ?)
            """,
            (_timestamp(minutes_ago=30), _timestamp(minutes_ago=30), _timestamp()),
        )
        conn.execute(
            """
            INSERT INTO runtime_executions (
                runtime_execution_id, task_id, turn_id, execution_seq, runtime_generation,
                status, native_runtime_kind, native_runtime_ref, native_turn_kind,
                native_turn_ref, created_at, started_at, updated_at
            ) VALUES ('normal-runtime-execution', 'normal-runtime-task', 'normal-runtime-turn',
                      1, 1, 'running', 'codex-process', 'runtime-normal',
                      'codex-thread', 'thread-normal', ?, ?, ?)
            """,
            (_timestamp(minutes_ago=30), _timestamp(minutes_ago=30), _timestamp()),
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 1
    assert (
        'ainrf_domain_turn_submission_entries{state="stale_delivering"} 0.0' in get_metrics_text()
    )


def test_delivery_unknown_submission_remains_operator_visible(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        conn.execute(
            """
            INSERT INTO turn_submissions (
                submission_id, task_id, reserved_turn_id, actor_user_id,
                idempotency_key, request_hash, status, input_json,
                failure_code, created_at, updated_at
            ) VALUES ('unknown-submission', 'telemetry-task', 'unknown-turn',
                      'telemetry-user', 'unknown-key', 'unknown-hash', 'delivery_unknown',
                      '{"text":"uncertain delivery"}', 'worker_lost_during_delivery', ?, ?)
            """,
            (_timestamp(minutes_ago=10), _timestamp(minutes_ago=9)),
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 2
    assert (
        'ainrf_domain_turn_submission_entries{state="delivery_unknown"} 1.0' in get_metrics_text()
    )


def test_blocked_next_turn_is_not_counted_as_ready_submission_backlog(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)
    control_path = tmp_path / "runtime" / "agentic_researcher.sqlite3"
    with closing(connect(control_path)) as conn:
        conn.execute(
            """
            INSERT INTO task_turns (
                turn_id, task_id, turn_seq, status, engine_family, engine_driver,
                contract_version, accepted_at, started_at, updated_at
            ) VALUES ('blocking-turn', 'telemetry-task', 1, 'in_progress',
                      'codex', 'codex-app-server', 1, ?, ?, ?)
            """,
            (_timestamp(minutes_ago=30), _timestamp(minutes_ago=30), _timestamp()),
        )
        conn.execute(
            """
            INSERT INTO turn_submissions (
                submission_id, task_id, reserved_turn_id, actor_user_id,
                idempotency_key, request_hash, status, input_json, created_at, updated_at
            ) VALUES ('blocked-submission', 'telemetry-task', 'blocked-turn',
                      'telemetry-user', 'blocked-key', 'blocked-hash', 'queued',
                      '{"text":"wait for prior turn"}', ?, ?)
            """,
            (_timestamp(minutes_ago=20), _timestamp(minutes_ago=20)),
        )
        conn.execute(
            """
            INSERT INTO conversation_submission_intents (
                submission_id, task_id, kind, retry_of_turn_id, created_at
            ) VALUES ('blocked-submission', 'telemetry-task', 'next_turn', NULL, ?)
            """,
            (_timestamp(minutes_ago=20),),
        )
        conn.execute(
            """
            INSERT INTO next_turn_submissions (
                submission_id, task_id, blocking_turn_id, status, created_at, updated_at
            ) VALUES ('blocked-submission', 'telemetry-task', 'blocking-turn',
                      'waiting', ?, ?)
            """,
            (_timestamp(minutes_ago=20), _timestamp(minutes_ago=20)),
        )
        conn.commit()

    snapshot = refresh_domain_metrics(tmp_path)

    assert snapshot.submission_backlog_count == 1
    assert 'ainrf_domain_turn_submission_entries{state="queued"} 1.0' in get_metrics_text()


def test_durable_counter_labels_reject_unbounded_values_and_tampering(tmp_path: Path) -> None:
    _seed_control_plane(tmp_path)

    assert not domain_telemetry._persist_durable_counter(
        "ainrf_domain_idempotency_requests_total",
        {"outcome": "attacker-controlled-value"},
        state_root=tmp_path,
    )
    domain_telemetry.record_idempotency_event("accepted", state_root=tmp_path)
    sidecar = tmp_path / "runtime" / "domain_telemetry.sqlite3"
    with closing(sqlite3.connect(sidecar)) as conn:
        conn.execute(
            "UPDATE domain_telemetry_counter_totals SET labels_json = ?",
            ('{"outcome":"attacker-controlled-value"}',),
        )
        conn.commit()

    with pytest.raises(domain_telemetry._TelemetryStoreError):
        domain_telemetry._load_durable_counters(tmp_path)


def test_read_only_connection_is_closed_after_active_user_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyCursor:
        def fetchall(self) -> list[object]:
            return []

    class ReadOnlyConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str) -> EmptyCursor:
            assert "sqlite_master" in query
            return EmptyCursor()

        def close(self) -> None:
            self.closed = True

    auth_path = tmp_path / "auth.sqlite3"
    auth_path.touch()
    connection = ReadOnlyConnection()
    monkeypatch.setattr(domain_telemetry, "_read_only", lambda _path: connection)

    assert domain_telemetry._active_user_ids(auth_path) == ()
    assert connection.closed is True


def test_project_module_durable_idempotency_reuse_and_conflict_are_observed(
    state_root: Path, committed_v2_state: str
) -> None:
    projects = build_domain_modules(state_root, artifact_sha=committed_v2_state).projects
    actor: dict[str, object] = {"id": "telemetry-user", "role": "member"}

    with structlog.testing.capture_logs() as logs:
        first = projects.create_project(actor, name="Telemetry", idempotency_key="durable-key")
        replay = projects.create_project(actor, name="Telemetry", idempotency_key="durable-key")
    assert replay == first
    reused = next(item for item in logs if item.get("outcome") == "reused")
    assert reused["user_id"] == "telemetry-user"
    assert "idempotency_key_fingerprint" in reused
    assert "durable-key" not in reused.values()

    with pytest.raises(DomainConflictError, match="different request"):
        projects.create_project(actor, name="Other", idempotency_key="durable-key")

    text = get_metrics_text()
    assert 'ainrf_domain_idempotency_requests_total{outcome="reused"} 1.0' in text
    assert 'ainrf_domain_idempotency_requests_total{outcome="conflict"} 1.0' in text


def test_shared_connection_records_sqlite_execution_errors(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "telemetry.sqlite3")) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT missing_column FROM missing_table")

    text = get_metrics_text()
    assert "ainrf_domain_sqlite_errors_total" in text
    assert 'operation="connection_execute"' in text
    assert 'error_type="OperationalError"' in text


def test_domain_alert_baseline_has_required_release_gates() -> None:
    rules_path = (
        Path(__file__).resolve().parents[1] / "deploy/config/prometheus/rules/ainrf-alerts.yml"
    )
    document = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    groups = document.get("groups")
    assert isinstance(groups, list)
    rules = {
        str(rule["alert"]): rule
        for group in groups
        if isinstance(group, dict)
        for rule in group.get("rules", [])
        if isinstance(rule, dict) and isinstance(rule.get("alert"), str)
    }

    assert "ainrf_domain_turn_submission_oldest_pending_age_seconds" in str(
        rules["AINRFTurnSubmissionBacklogAgeWarning"]["expr"]
    )
    assert "> 300" in str(rules["AINRFTurnSubmissionBacklogAgeWarning"]["expr"])
    assert "> 900" in str(rules["AINRFTurnSubmissionBacklogAgeCritical"]["expr"])
    assert "> 900" in str(rules["AINRFLiteratureResearchTaskPending"]["expr"])
    assert "> 108000" in str(rules["AINRFOverviewSnapshotStale"]["expr"])
    assert "ainrf_domain_metrics_scrape_success" in str(
        rules["AINRFDomainMetricScrapeFailed"]["expr"]
    )
    assert rules["AINRFDomainMetricScrapeFailed"]["labels"]["severity"] == "critical"
    assert "ainrf_domain_metrics_risk_state_known" in str(
        rules["AINRFDomainMetricRiskStateUnknown"]["expr"]
    )
    assert rules["AINRFDomainMetricRiskStateUnknown"]["labels"]["severity"] == "critical"
    source_not_ready_expr = str(rules["AINRFDomainTelemetrySourceNotReady"]["expr"])
    assert "ainrf_domain_telemetry_source_status" in source_not_ready_expr
    assert rules["AINRFDomainTelemetrySourceNotReady"]["labels"]["severity"] == "critical"
    release_gate_expr = str(rules["AINRFDomainTelemetryReleaseGateBlocked"]["expr"])
    assert "ainrf_domain_metrics_scrape_success" in release_gate_expr
    assert "ainrf_domain_metrics_risk_state_known" in release_gate_expr
    assert "ainrf_domain_telemetry_delivery_failure_latched" in release_gate_expr
    assert "absent(" in release_gate_expr
    assert "up{" in release_gate_expr
    assert rules["AINRFDomainTelemetryReleaseGateBlocked"]["labels"]["release_gate"] == "B"
    assert "delivery_unknown" in str(rules["AINRFTurnSubmissionDeliveryUnknown"]["expr"])
    assert rules["AINRFTurnSubmissionDeliveryUnknown"]["labels"]["severity"] == "critical"
    assert rules["AINRFDomainTelemetryEventDeliveryFailure"]["labels"]["release_gate"] == "B"
    assert "ainrf_domain_overview_attention_required" in str(
        rules["AINRFOverviewAttentionRequired"]["expr"]
    )
