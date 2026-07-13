"""Unit tests for ainrf.backup — create, verify, restore roundtrip."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tarfile
from io import BytesIO
import json
from pathlib import Path

import pytest

import ainrf.backup.service as backup_service
from ainrf.auth.service import AuthService
from ainrf.backup.service import BackupManifest, BackupService, _dump_sqlite_safe
from ainrf.domain_control import (
    CUTOVER_REQUIRED_PARTICIPANT_TYPES,
    DomainCutoverController,
    DomainMaintenanceService,
)
from ainrf.domain_migration import DomainImporter, DomainReconciliationService, ReconciliationReport
from tests.domain_cutover_fixtures import prepare_committed_v2_cutover

pytestmark = [pytest.mark.unit]


# ── helpers ───────────────────────────────────────────────────────


def _seed_state(state_root: Path) -> None:
    """Populate a minimal state_root with databases and config."""
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    # Create two SQLite databases with a row each
    for db_name in ("auth.sqlite3", "sessions.sqlite3"):
        conn = sqlite3.connect(str(runtime / db_name))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('hello')")
        conn.commit()
        conn.close()

    # Top-level config
    (state_root / "config.json").write_text('{"api_key_hashes": []}', encoding="utf-8")
    (state_root / "search-settings.json").write_text(
        '{"active_backend": "semantic_scholar"}', encoding="utf-8"
    )

    # Runtime config
    (runtime / "projects.json").write_text('{"default": {}}', encoding="utf-8")
    (runtime / "workspaces.json").write_text('{"default": {}}', encoding="utf-8")

    # State subdirectory
    ss = state_root / "session-states" / "task-abc"
    ss.mkdir(parents=True)
    (ss / "checkpoint.json").write_text('{"step": 1}', encoding="utf-8")


def _enter_drained_maintenance(state_root: Path) -> DomainMaintenanceService:
    """Create the full persisted maintenance proof required for promotion."""

    maintenance = DomainMaintenanceService(state_root)
    maintenance.initialize()
    participant_ids: list[str] = []
    for participant_type in CUTOVER_REQUIRED_PARTICIPANT_TYPES:
        participant_id = f"backup-test:{participant_type}"
        maintenance.register_participant(participant_id, participant_type)
        participant_ids.append(participant_id)
    maintenance.enter(actor_id="backup-test", reason="verify generation promotion")
    for participant_id in participant_ids:
        maintenance.drain_participant(participant_id)
    return maintenance


def test_sqlite_backup_can_snapshot_a_read_only_source(tmp_path: Path) -> None:
    """Source snapshots must work from a read-only source directory in WAL mode."""

    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "source.sqlite3"
    destination = tmp_path / "snapshot.sqlite3"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO records (value) VALUES ('source')")
        connection.commit()
        source_root.chmod(0o555)
        _dump_sqlite_safe(source, destination)
    finally:
        source_root.chmod(0o755)
        connection.close()

    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("source",)]


def test_backup_preserves_an_empty_discovered_sqlite_member(tmp_path: Path) -> None:
    """A complete v3 inventory includes an inert zero-byte SQLite placeholder."""

    state_root = tmp_path / "state"
    _seed_state(state_root)
    invalid_source = state_root / "runtime" / "ainrf.sqlite3"
    invalid_source.touch()

    archive = BackupService(state_root).create_backup(tmp_path / "backup.tar.gz")
    manifest = BackupService(state_root).verify_backup(archive)

    assert "ainrf.sqlite3" in manifest.databases


def test_sqlite_backup_can_snapshot_a_read_only_file_source(tmp_path: Path) -> None:
    """A non-WAL source remains readable when only its file is read-only."""

    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (value) VALUES ('source')")
    source.chmod(0o444)
    try:
        _dump_sqlite_safe(source, destination)
    finally:
        source.chmod(0o644)

    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("source",)]


def test_sqlite_backup_retries_a_changed_staged_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient raw-copy race retries instead of rejecting a valid backup."""

    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (value) VALUES ('source')")

    def unavailable_online_snapshot(_source: Path, _dest: Path, *, deadline: float) -> None:
        _ = deadline
        raise sqlite3.OperationalError("readonly WAL shared memory")

    real_fingerprint = backup_service._sqlite_source_fingerprint
    fingerprint_calls = 0

    def changes_once(
        members: tuple[Path, ...],
    ) -> tuple[tuple[str, int, int, int, str], ...]:
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        fingerprint = real_fingerprint(members)
        if fingerprint_calls == 2:
            return fingerprint + (("simulated-source-change", 0, 0, 0, ""),)
        return fingerprint

    monkeypatch.setattr(backup_service, "_dump_sqlite_online", unavailable_online_snapshot)
    monkeypatch.setattr(backup_service, "_sqlite_source_fingerprint", changes_once)
    monkeypatch.setattr(backup_service, "_SQLITE_SNAPSHOT_RETRY_INTERVAL_SECONDS", 0.0)

    _dump_sqlite_safe(source, destination)

    assert fingerprint_calls >= 4
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM records").fetchall() == [("source",)]


def test_sqlite_backup_rejects_unavailable_fallback_after_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only fallback never writes an archive after its deadline expires."""

    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")

    def unavailable_online_snapshot(_source: Path, _dest: Path, *, deadline: float) -> None:
        _ = deadline
        raise sqlite3.OperationalError("readonly WAL shared memory")

    monkeypatch.setattr(backup_service, "_dump_sqlite_online", unavailable_online_snapshot)
    monkeypatch.setattr(backup_service, "_SQLITE_SNAPSHOT_DEADLINE_SECONDS", 0.0)

    with pytest.raises(ValueError, match="did not stabilize before snapshot deadline"):
        _dump_sqlite_safe(source, destination)

    assert not destination.exists()


def _write_v2_archive(
    archive: Path,
    *,
    database: Path,
    config: Path,
    auth_schema_version: int | None = None,
) -> Path:
    """Write the on-disk manifest format emitted by backup manifest v2."""
    manifest = {
        "version": 2,
        "created_at": "2026-07-12T00:00:00+00:00",
        "databases": {
            "auth.sqlite3": {
                "size": database.stat().st_size,
                "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                "source_path": "runtime/auth.sqlite3",
                "schema_version": auth_schema_version,
            }
        },
        "config_files": {
            "config.json": {
                "size": config.stat().st_size,
                "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                "source_path": "config.json",
                "schema_version": None,
            }
        },
        "includes_workspaces": False,
        "includes_tenants": False,
    }
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(database, arcname="databases/auth.sqlite3")
        tar.add(config, arcname="config/config.json")
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, BytesIO(manifest_bytes))
    return archive


class _RejectingRestoreValidator:
    def __init__(self, candidates: list[Path]) -> None:
        self._candidates = candidates

    def __call__(self, candidate_root: Path, manifest: BackupManifest) -> None:
        self._candidates.append(candidate_root)
        assert candidate_root.exists()
        assert (candidate_root / "runtime" / "auth.sqlite3").exists()
        assert manifest.version == 3
        raise ValueError("reconciliation rejected staged restore")


def _rewrite_v3_member_metadata(
    archive: Path,
    destination: Path,
    *,
    member_name: str,
    uid: int,
    gid: int,
    mode: int,
    update_manifest: bool,
) -> Path:
    """Rewrite one v3 member's POSIX metadata, optionally keeping its manifest aligned."""

    with tarfile.open(archive, "r:gz") as source, tarfile.open(destination, "w:gz") as target:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == member_name:
                member.uid = uid
                member.gid = gid
                member.mode = mode
                target.addfile(member, data)
                continue
            if member.name == "manifest.json" and update_manifest:
                assert data is not None
                payload = json.loads(data.read().decode("utf-8"))
                metadata = payload["files"][member_name]
                metadata["uid"] = uid
                metadata["gid"] = gid
                metadata["mode"] = mode
                replacement = json.dumps(payload).encode("utf-8")
                manifest_info = tarfile.TarInfo("manifest.json")
                manifest_info.size = len(replacement)
                target.addfile(manifest_info, BytesIO(replacement))
                continue
            target.addfile(member, data)
    return destination


# ── tests ─────────────────────────────────────────────────────────


def test_create_backup_captures_databases(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")

    assert archive.exists()
    assert archive.suffix == ".gz"
    # Archive should be readable
    manifest = svc.verify_backup(archive)
    assert manifest.version == 3
    assert "auth.sqlite3" in manifest.databases
    assert "sessions.sqlite3" in manifest.databases
    assert "config.json" in manifest.config_files
    assert "projects.json" in manifest.config_files
    assert "workspaces.json" in manifest.config_files
    assert manifest.config_files["workspaces.json"].source_path == "runtime/workspaces.json"
    assert not manifest.includes_workspaces


def test_create_backup_skips_missing_dbs(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    (state_root / "runtime").mkdir(parents=True)
    # Only one DB exists
    conn = sqlite3.connect(str(state_root / "runtime" / "auth.sqlite3"))
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")
    manifest = svc.verify_backup(archive)

    assert "auth.sqlite3" in manifest.databases
    assert "sessions.sqlite3" not in manifest.databases


def test_verify_rejects_corrupted_archive(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    svc = BackupService(state_root)
    archive = svc.create_backup(tmp_path / "out")

    # Corrupt the archive by truncating
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])

    with pytest.raises(Exception):
        svc.verify_backup(archive)


def test_restore_roundtrip(tmp_path: Path) -> None:
    src_root = tmp_path / "src-state"
    _seed_state(src_root)

    svc = BackupService(src_root)
    archive = svc.create_backup(tmp_path / "out")

    # Restore into a fresh directory
    dst_root = tmp_path / "dst-state"
    dst_svc = BackupService(dst_root)
    dst_svc.restore_backup(archive, target_state_root=dst_root, skip_pre_backup=True)

    # Verify databases restored
    for db_name in ("auth.sqlite3", "sessions.sqlite3"):
        conn = sqlite3.connect(str(dst_root / "runtime" / db_name))
        rows = conn.execute("SELECT v FROM t").fetchall()
        conn.close()
        assert rows == [("hello",)]

    # Verify config restored
    assert (dst_root / "config.json").read_text() == '{"api_key_hashes": []}'
    assert (dst_root / "search-settings.json").exists()
    assert (dst_root / "runtime" / "projects.json").exists()

    # Verify state subdirectory restored
    assert (
        dst_root / "session-states" / "task-abc" / "checkpoint.json"
    ).read_text() == '{"step": 1}'


def test_restore_creates_pre_backup(tmp_path: Path) -> None:
    src_root = tmp_path / "src-state"
    _seed_state(src_root)

    svc = BackupService(src_root)
    archive = svc.create_backup(tmp_path / "archives" / "test.tar.gz")

    # Restore with pre-backup enabled (default)
    dst_root = tmp_path / "dst-state"
    _seed_state(dst_root)  # existing data

    dst_svc = BackupService(dst_root)
    staged_root = tmp_path / "staged-state"
    dst_svc.restore_backup(archive, target_state_root=staged_root)  # pre-backup defaults to True

    # A pre-restore backup should exist alongside the archive
    pre_backups = list(archive.parent.glob("pre-restore-*.tar.gz"))
    assert len(pre_backups) == 1
    assert (dst_root / "runtime" / "projects.json").exists()


def test_backup_includes_workspaces(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)

    ws_root = tmp_path / "ws"
    (ws_root / "project1").mkdir(parents=True)
    (ws_root / "project1" / "README.md").write_text("# project1", encoding="utf-8")

    svc = BackupService(state_root)
    archive = svc.create_backup(
        tmp_path / "out.tar.gz",
        include_workspaces=True,
        workspace_root=ws_root,
    )
    manifest = svc.verify_backup(archive)
    assert manifest.includes_workspaces

    # Restore with workspace
    dst_root = tmp_path / "dst-state"
    dst_ws = tmp_path / "dst-ws"
    dst_svc = BackupService(dst_root)
    dst_svc.restore_backup(
        archive,
        target_state_root=dst_root,
        target_workspace_root=dst_ws,
        skip_pre_backup=True,
    )
    assert (dst_ws / "project1" / "README.md").read_text() == "# project1"


def test_verify_missing_archive(tmp_path: Path) -> None:
    svc = BackupService(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.verify_backup(tmp_path / "nonexistent.tar.gz")


def test_restore_missing_archive(tmp_path: Path) -> None:
    svc = BackupService(tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.restore_backup(tmp_path / "nonexistent.tar.gz")


def test_restore_requires_new_staged_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")

    existing_root = tmp_path / "existing"
    existing_root.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        BackupService(source_root).restore_backup(archive, target_state_root=existing_root)


def test_restore_rejects_nested_state_and_workspace_targets_before_staging(tmp_path: Path) -> None:
    """A Workspace candidate must never create the state target as its parent."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    workspace_root = tmp_path / "source-workspaces"
    workspace_root.mkdir()
    (workspace_root / "README.md").write_text("workspace", encoding="utf-8")
    archive = BackupService(source_root).create_backup(
        tmp_path / "archive.tar.gz",
        include_workspaces=True,
        workspace_root=workspace_root,
    )
    state_target = tmp_path / "generation"

    with pytest.raises(
        ValueError, match="target_state_root and target_workspace_root must not overlap"
    ):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=state_target,
            target_workspace_root=state_target / "workspaces",
            skip_pre_backup=True,
        )

    assert not state_target.exists()


def test_restore_rejects_nested_workspace_and_tenant_targets_before_staging(tmp_path: Path) -> None:
    """Independent high-risk promotion roots must not create each other."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    workspace_target = tmp_path / "workspaces"

    with pytest.raises(
        ValueError, match="target_workspace_root and target_tenant_root must not overlap"
    ):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=tmp_path / "generation",
            target_workspace_root=workspace_target,
            target_tenant_root=workspace_target / "tenants",
            skip_pre_backup=True,
        )

    assert not workspace_target.exists()


def test_verify_rejects_checksum_tampering(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "config/projects.json":
                replacement = b'{"changed": {}}'
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(ValueError, match="checksum mismatch"):
        BackupService(source_root).verify_backup(tampered)


def test_manifest_v3_inventories_every_nested_state_member(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    (state_root / "detections" / "env-host").mkdir(parents=True)
    (state_root / "detections" / "env-host" / "snapshot.json").write_text(
        '{"status": "ok"}', encoding="utf-8"
    )
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "project" / "nested").mkdir(parents=True)
    (workspace_root / "project" / "nested" / "note.txt").write_text("note", encoding="utf-8")
    tenant_root = tmp_path / "tenants"
    (tenant_root / "alice" / ".config").mkdir(parents=True)
    (tenant_root / "alice" / ".config" / "settings.json").write_text("{}", encoding="utf-8")

    archive = BackupService(state_root).create_backup(
        tmp_path / "archive.tar.gz",
        include_workspaces=True,
        workspace_root=workspace_root,
        include_tenants=True,
        tenant_root=tenant_root,
    )

    manifest = BackupService(state_root).verify_backup(archive)
    assert manifest.version == 3
    assert manifest.includes_workspaces
    assert manifest.includes_tenants
    assert manifest.tree_sha256
    assert {
        "session-states/task-abc/checkpoint.json",
        "detections/env-host/snapshot.json",
        "workspaces/project/nested/note.txt",
        "tenants/alice/.config/settings.json",
    } <= set(manifest.files)
    assert manifest.files["workspaces/project/nested/note.txt"].mode is not None
    assert manifest.files["workspaces/project/nested/note.txt"].uid is not None


def test_manifest_v3_roundtrips_all_runtime_json_sqlite_and_future_state_dirs(
    tmp_path: Path,
) -> None:
    """A v3 control-plane backup must not lose newly added legacy sources."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    runtime = source_root / "runtime"
    runtime_json = {
        "environments.json": '{"items": [{"id": "env-legacy"}]}\n',
        "sessions.json": '{"items": [{"session_id": "session-legacy"}]}\n',
        "skill_registries.json": '{"skills": [{"id": "registry-legacy"}]}\n',
    }
    for name, content in runtime_json.items():
        (runtime / name).write_text(content, encoding="utf-8")
    nested_runtime_json = runtime / "future" / "registry.json"
    nested_runtime_json.parent.mkdir()
    nested_runtime_json.write_text('{"future": true}\n', encoding="utf-8")
    future_database = runtime / "extensions" / "future.sqlite3"
    future_database.parent.mkdir()
    with sqlite3.connect(future_database) as connection:
        connection.execute("CREATE TABLE retained (value TEXT NOT NULL)")
        connection.execute("INSERT INTO retained(value) VALUES ('future-state')")
        connection.commit()
    future_state = source_root / "future-state" / "nested" / "checkpoint.json"
    future_state.parent.mkdir(parents=True)
    future_state.write_text('{"generation": 7}\n', encoding="utf-8")

    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    manifest = BackupService(source_root).verify_backup(archive)

    assert {
        "runtime/environments.json",
        "runtime/sessions.json",
        "runtime/skill_registries.json",
        "runtime/future/registry.json",
    } <= set(manifest.config_files)
    assert "extensions/future.sqlite3" in manifest.databases
    assert {
        "config/runtime/environments.json",
        "config/runtime/sessions.json",
        "config/runtime/skill_registries.json",
        "config/runtime/future/registry.json",
        "databases/extensions/future.sqlite3",
        "future-state/nested/checkpoint.json",
    } <= set(manifest.files)

    restored_root = tmp_path / "restored"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=restored_root,
        skip_pre_backup=True,
    )

    for name, content in runtime_json.items():
        assert (restored_root / "runtime" / name).read_text(encoding="utf-8") == content
    assert (restored_root / "runtime" / "future" / "registry.json").read_text(
        encoding="utf-8"
    ) == '{"future": true}\n'
    assert (restored_root / "future-state" / "nested" / "checkpoint.json").read_text(
        encoding="utf-8"
    ) == '{"generation": 7}\n'
    with sqlite3.connect(restored_root / "runtime" / "extensions" / "future.sqlite3") as connection:
        assert connection.execute("SELECT value FROM retained").fetchall() == [("future-state",)]


def test_manifest_v3_binds_posix_metadata_to_archive_and_restored_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    source_config = source_root / "config.json"
    source_checkpoint = source_root / "session-states" / "task-abc" / "checkpoint.json"
    source_config.chmod(0o640)
    source_checkpoint.chmod(0o600)
    workspace_root = tmp_path / "source-workspaces"
    workspace_file = workspace_root / "project" / "README.md"
    workspace_file.parent.mkdir(parents=True)
    workspace_file.write_text("workspace", encoding="utf-8")
    workspace_file.chmod(0o640)

    archive = BackupService(source_root).create_backup(
        tmp_path / "archive.tar.gz",
        include_workspaces=True,
        workspace_root=workspace_root,
    )
    manifest = BackupService(source_root).verify_backup(archive)

    for member_name, source_path in {
        "config/config.json": source_config,
        "session-states/task-abc/checkpoint.json": source_checkpoint,
        "workspaces/project/README.md": workspace_file,
    }.items():
        meta = manifest.files[member_name]
        source_stat = source_path.stat()
        assert meta.mode == source_stat.st_mode & 0o7777
        assert meta.uid == source_stat.st_uid
        assert meta.gid == source_stat.st_gid
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember(member_name)
        assert member.mode & 0o7777 == meta.mode
        assert member.uid == meta.uid
        assert member.gid == meta.gid

    target_state = tmp_path / "restored"
    target_workspace = tmp_path / "restored-workspaces"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=target_state,
        target_workspace_root=target_workspace,
        skip_pre_backup=True,
    )

    for member_name, restored_path in {
        "config/config.json": target_state / "config.json",
        "session-states/task-abc/checkpoint.json": (
            target_state / "session-states" / "task-abc" / "checkpoint.json"
        ),
        "workspaces/project/README.md": target_workspace / "project" / "README.md",
    }.items():
        meta = manifest.files[member_name]
        restored_stat = restored_path.stat()
        assert restored_stat.st_mode & 0o7777 == meta.mode
        assert restored_stat.st_uid == meta.uid
        assert restored_stat.st_gid == meta.gid

    high_risk_report = json.loads(
        (target_state / backup_service._HIGH_RISK_RESTORE_REPORT_NAME).read_text(encoding="utf-8")
    )
    assert high_risk_report["operator_action_required"] is True
    assert high_risk_report["automatic_git_changes_applied"] is False
    assert high_risk_report["trees"][0]["kind"] == "workspaces"
    assert high_risk_report["trees"][0]["orphan_artifacts"]["status"] == "operator_review_required"
    assert "project/README.md" in high_risk_report["trees"][0]["restored_paths"]
    assert str(target_workspace) not in json.dumps(high_risk_report)


def test_verify_rejects_mode_uid_and_gid_tampering(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    member_name = "config/config.json"
    with tarfile.open(archive, "r:gz") as tar:
        original = tar.getmember(member_name)
    tampered = _rewrite_v3_member_metadata(
        archive,
        tmp_path / "metadata-tampered.tar.gz",
        member_name=member_name,
        uid=original.uid + 1,
        gid=original.gid + 1,
        mode=(original.mode ^ 0o100) & 0o7777,
        update_manifest=False,
    )

    with pytest.raises(ValueError) as error:
        BackupService(source_root).verify_backup(tampered)

    message = str(error.value)
    assert f"{member_name}: mode mismatch" in message
    assert f"{member_name}: uid mismatch" in message
    assert f"{member_name}: gid mismatch" in message


def test_restore_rejects_unrestorable_owner_before_promotion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    original_config = (source_root / "config.json").read_bytes()
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    member_name = "config/config.json"
    with tarfile.open(archive, "r:gz") as tar:
        original = tar.getmember(member_name)
    aligned = _rewrite_v3_member_metadata(
        archive,
        tmp_path / "owner-aligned.tar.gz",
        member_name=member_name,
        uid=original.uid + 100_000,
        gid=original.gid + 100_000,
        mode=original.mode,
        update_manifest=True,
    )

    def reject_chown(path: Path, uid: int, gid: int) -> None:
        raise PermissionError(f"cannot chown {path} to {uid}:{gid}")

    monkeypatch.setattr(backup_service.os, "chown", reject_chown)
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="cannot restore ownership"):
        BackupService(source_root).restore_backup(
            aligned,
            target_state_root=target,
            skip_pre_backup=True,
        )

    assert not target.exists()
    assert (source_root / "config.json").read_bytes() == original_config
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_restore_always_runs_default_domain_validator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    candidates: list[Path] = []

    def reject_default_validator(candidate_root: Path, manifest: BackupManifest) -> None:
        candidates.append(candidate_root)
        assert manifest.version == 3
        raise ValueError("default reconciliation rejected staged restore")

    monkeypatch.setattr(
        backup_service,
        "validate_staged_domain_restore",
        reject_default_validator,
    )
    with pytest.raises(ValueError, match="default reconciliation rejected staged restore"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
            validators=(),
        )

    assert candidates
    assert not target.exists()
    assert all(not candidate.exists() for candidate in candidates)


def test_restore_runs_domain_reconciliation_against_disposable_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    auth = AuthService(state_root=source_root)
    auth.initialize()
    user = auth.register(
        username="restore-owner", display_name="Restore owner", password="safe-password"
    )
    workspace_path = source_root / "workspace"
    workspace_path.mkdir()
    runtime = source_root / "runtime"
    (runtime / "projects.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "project_id": "restore-project",
                        "name": "Restore project",
                        "owner_user_id": user.id,
                        "is_default": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (runtime / "workspaces.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "workspace_id": "restore-workspace",
                        "project_id": "restore-project",
                        "owner_user_id": user.id,
                        "default_workdir": str(workspace_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    imported = DomainImporter(source_root).run(artifact_sha="a" * 64)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    calls: list[tuple[Path, str | None]] = []
    original_reconcile = DomainReconciliationService.reconcile

    def record_reconcile(
        service: DomainReconciliationService, run_id: str | None = None
    ) -> ReconciliationReport:
        calls.append((service._state_root, run_id))
        return original_reconcile(service, run_id)

    monkeypatch.setattr(DomainReconciliationService, "reconcile", record_reconcile)
    target = tmp_path / "restored"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    assert len(calls) == 1
    reconciliation_root, run_id = calls[0]
    assert run_id == imported.run_id
    assert reconciliation_root != target
    assert not reconciliation_root.exists()
    assert target.exists()


def test_restore_reconciles_committed_v2_before_promotion(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    prepare_committed_v2_cutover(source_root, tmp_path)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"

    BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    assert DomainCutoverController(target).status().state == "v2"


def test_v2_control_plane_restore_writes_privacy_safe_orphan_report(tmp_path: Path) -> None:
    """An unselected Workspace/tenant tree cannot suppress the v2 risk report."""

    source_root = tmp_path / "source"
    prepare_committed_v2_cutover(source_root, tmp_path)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"

    BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    report = json.loads(
        (target / backup_service._HIGH_RISK_RESTORE_REPORT_NAME).read_text(encoding="utf-8")
    )
    control_plane = report["control_plane_restore"]
    assert report["operator_action_required"] is True
    assert report["automatic_git_changes_applied"] is False
    assert control_plane["domain_mode"] == "v2"
    assert control_plane["workspace_tenant_data_restored"] is False
    assert control_plane["orphan_artifacts"]["status"] == "operator_review_required"
    assert control_plane["git_change_report"]["status"] == (
        "not_collected_without_explicit_restore_tree"
    )
    assert str(source_root) not in json.dumps(report)


def test_verify_rejects_tampered_nested_state_member(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    archive = BackupService(state_root).create_backup(tmp_path / "archive.tar.gz")
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "session-states/task-abc/checkpoint.json":
                replacement = b'{"step": 9}'
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(
        ValueError, match="session-states/task-abc/checkpoint.json: checksum mismatch"
    ):
        BackupService(state_root).verify_backup(tampered)


def test_verify_rejects_include_flag_mismatch(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _seed_state(state_root)
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    (workspace_root / "README.md").write_text("workspace", encoding="utf-8")
    archive = BackupService(state_root).create_backup(
        tmp_path / "archive.tar.gz", include_workspaces=True, workspace_root=workspace_root
    )
    tampered = tmp_path / "flag-mismatch.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as dest:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name == "manifest.json":
                assert data is not None
                payload = json.loads(data.read().decode("utf-8"))
                payload["includes_workspaces"] = False
                replacement = json.dumps(payload).encode("utf-8")
                copy = tarfile.TarInfo(member.name)
                copy.size = len(replacement)
                dest.addfile(copy, BytesIO(replacement))
            else:
                dest.addfile(member, data)

    with pytest.raises(
        ValueError, match="workspaces: include flag does not match archive contents"
    ):
        BackupService(state_root).verify_backup(tampered)


def test_v2_archive_remains_verifiable_and_restorable(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    database = source_root / "runtime" / "auth.sqlite3"
    config = source_root / "config.json"
    archive = _write_v2_archive(tmp_path / "v2.tar.gz", database=database, config=config)

    service = BackupService(source_root)
    assert service.verify_backup(archive).version == 2
    target = tmp_path / "restored"
    service.restore_backup(archive, target_state_root=target, skip_pre_backup=True)
    assert (target / "runtime" / "auth.sqlite3").exists()
    assert (target / "config.json").read_text(encoding="utf-8") == config.read_text(
        encoding="utf-8"
    )


def test_restore_rejects_manifest_schema_version_before_promotion(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    database = source_root / "runtime" / "auth.sqlite3"
    conn = sqlite3.connect(str(database))
    conn.execute(
        "CREATE TABLE _schema_version (database TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO _schema_version (database, version) VALUES ('auth', 7)")
    conn.commit()
    conn.close()

    target = tmp_path / "schema-mismatch"
    archive = _write_v2_archive(
        tmp_path / "schema-mismatch.tar.gz",
        database=database,
        config=source_root / "config.json",
        auth_schema_version=8,
    )

    with pytest.raises(ValueError, match="schema version mismatch"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
        )

    assert not target.exists()
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_restore_runs_custom_validator_before_promotion_and_cleans_candidate(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    candidates: list[Path] = []
    validator = _RejectingRestoreValidator(candidates)

    with pytest.raises(ValueError, match="reconciliation rejected staged restore"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
            validators=(validator,),
        )

    assert not target.exists()
    assert candidates
    assert all(not candidate.exists() for candidate in candidates)
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_restore_removes_promotion_journal_after_success(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    journal = target.parent / f".{target.name}.restore-promotion.json"

    restored = BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    assert restored == target
    assert (target / "runtime" / "auth.sqlite3").exists()
    assert not journal.exists()


def test_restore_seals_generation_and_active_pointer_promotion_preserves_old_root(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    _enter_drained_maintenance(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )

    attestation = json.loads(
        (generation / backup_service._RESTORE_GENERATION_ATTESTATION_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert attestation["version"] == backup_service._RESTORE_GENERATION_ATTESTATION_VERSION
    assert attestation["manifest_digest"] == backup_service._manifest_digest(
        BackupService(source_root).verify_backup(archive)
    )

    active_pointer = tmp_path / "active-state"
    os.symlink(str(source_root), active_pointer)

    result = BackupService(source_root).promote_restored_generation(
        generation,
        active_state_pointer=active_pointer,
        maintenance_stability_window_seconds=0,
    )

    assert result.active_pointer == active_pointer
    assert result.generation_root == generation.resolve()
    assert result.previous_generation_root == source_root.resolve()
    assert active_pointer.resolve() == generation.resolve()
    assert (source_root / "runtime" / "auth.sqlite3").exists()
    assert not backup_service._active_generation_promotion_journal_path(active_pointer).exists()


def test_active_generation_promotion_rejects_unattested_directory(tmp_path: Path) -> None:
    generation = tmp_path / "not-a-restore"
    generation.mkdir()
    active_pointer = tmp_path / "active-state"

    with pytest.raises(ValueError, match="not a verified restore"):
        BackupService(generation).promote_restored_generation(
            generation,
            active_state_pointer=active_pointer,
        )

    assert not active_pointer.exists()


def test_active_generation_promotion_requires_a_ready_maintenance_epoch(tmp_path: Path) -> None:
    """A confirmation flag cannot replace the persisted writer-drain proof."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    active_pointer = tmp_path / "active-state"
    os.symlink(str(source_root), active_pointer)

    with pytest.raises(ValueError, match="staged generation.*maintenance control plane"):
        BackupService(source_root).promote_restored_generation(
            generation,
            active_state_pointer=active_pointer,
            maintenance_stability_window_seconds=0,
        )

    assert active_pointer.resolve() == source_root.resolve()


def test_active_generation_promotion_requires_the_staged_generation_to_be_fenced(
    tmp_path: Path,
) -> None:
    """The source drain alone cannot allow a newly selected root to reopen writers."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    DomainMaintenanceService(source_root).initialize()
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    _enter_drained_maintenance(source_root)
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    active_pointer = tmp_path / "active-state"
    os.symlink(str(source_root), active_pointer)

    with pytest.raises(ValueError, match="staged generation to remain in maintenance"):
        BackupService(source_root).promote_restored_generation(
            generation,
            active_state_pointer=active_pointer,
            maintenance_stability_window_seconds=0,
        )

    assert active_pointer.resolve() == source_root.resolve()


def test_active_generation_recovery_rejects_unsafe_journal_operation_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recovery must not turn a corrupt journal field into an outside path."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    old_generation = tmp_path / "old-generation"
    old_generation.mkdir()
    active_pointer = tmp_path / "active-state"
    os.symlink(str(old_generation), active_pointer)
    attestation = backup_service._read_restore_generation_attestation(generation)
    journal = backup_service._active_generation_promotion_journal_path(active_pointer)
    payload = backup_service._active_generation_promotion_payload(
        active_pointer=active_pointer,
        generation_root=generation.resolve(),
        previous_generation_root=old_generation.resolve(),
        attestation=attestation,
        operation_id="safe-operation",
    )
    payload["operation_id"] = "../../outside"
    backup_service._write_promotion_journal(journal, payload, exclusive=True)
    monkeypatch.setattr(backup_service, "_journal_process_is_alive", lambda _payload: False)

    with pytest.raises(ValueError, match="invalid operation id"):
        backup_service.recover_active_generation_promotion(active_pointer)

    assert not (tmp_path.parent / "outside.tmp").exists()
    assert journal.exists()


def test_active_generation_recovery_canonicalizes_parent_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A crash journal remains recoverable through an equivalent pointer spelling."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    old_generation = tmp_path / "old-generation"
    old_generation.mkdir()
    real_parent = tmp_path / "real-pointer-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "pointer-parent-alias"
    os.symlink(str(real_parent), alias_parent)
    alias_pointer = alias_parent / "active-state"
    resolved_pointer = real_parent / "active-state"
    os.symlink(str(old_generation), alias_pointer)
    attestation = backup_service._read_restore_generation_attestation(generation)
    journal = backup_service._active_generation_promotion_journal_path(alias_pointer)
    payload = backup_service._active_generation_promotion_payload(
        active_pointer=alias_pointer,
        generation_root=generation.resolve(),
        previous_generation_root=old_generation.resolve(),
        attestation=attestation,
        operation_id="canonical-recovery",
    )
    temporary_pointer, _, _ = backup_service._active_generation_journal_paths(
        payload,
        active_pointer=alias_pointer,
    )
    backup_service._write_promotion_journal(journal, payload, exclusive=True)
    os.symlink(str(generation.resolve()), temporary_pointer)
    payload["phase"] = "promoting"
    backup_service._write_promotion_journal(journal, payload)
    backup_service.os.replace(temporary_pointer, resolved_pointer)
    monkeypatch.setattr(backup_service, "_journal_process_is_alive", lambda _payload: False)

    recovered = backup_service.recover_active_generation_promotion(resolved_pointer)

    assert recovered is not None
    assert recovered.recovered is True
    assert resolved_pointer.resolve() == generation.resolve()
    assert not journal.exists()


def test_interrupted_active_generation_pointer_switch_is_finalized_on_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    old_generation = tmp_path / "old-generation"
    old_generation.mkdir()
    active_pointer = tmp_path / "active-state"
    os.symlink(str(old_generation), active_pointer)
    attestation = backup_service._read_restore_generation_attestation(generation)
    operation_id = "interrupted-pointer-switch"
    journal = backup_service._active_generation_promotion_journal_path(active_pointer)
    payload = backup_service._active_generation_promotion_payload(
        active_pointer=active_pointer,
        generation_root=generation.resolve(),
        previous_generation_root=old_generation.resolve(),
        attestation=attestation,
        operation_id=operation_id,
    )
    temporary_pointer, _, _ = backup_service._active_generation_journal_paths(
        payload,
        active_pointer=active_pointer,
    )
    backup_service._write_promotion_journal(journal, payload, exclusive=True)
    os.symlink(str(generation.resolve()), temporary_pointer)
    payload["phase"] = "promoting"
    backup_service._write_promotion_journal(journal, payload)
    backup_service.os.replace(temporary_pointer, active_pointer)
    monkeypatch.setattr(backup_service, "_journal_process_is_alive", lambda _payload: False)

    recovered = backup_service.recover_active_generation_promotion(active_pointer)

    assert recovered is not None
    assert recovered.recovered is True
    assert active_pointer.resolve() == generation.resolve()
    assert old_generation.exists()
    assert not journal.exists()


def test_active_generation_promotion_rolls_back_on_pointer_sync_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    _enter_drained_maintenance(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    generation = tmp_path / "restored-generation"
    BackupService(source_root).restore_backup(
        archive,
        target_state_root=generation,
        skip_pre_backup=True,
    )
    active_pointer = tmp_path / "active-state"
    os.symlink(str(source_root), active_pointer)
    journal = backup_service._active_generation_promotion_journal_path(active_pointer)
    real_fsync_directory = backup_service._fsync_directory
    failed = False

    def fail_after_pointer_switch(path: Path) -> None:
        nonlocal failed
        if (
            path == active_pointer.parent
            and active_pointer.is_symlink()
            and active_pointer.resolve() == generation.resolve()
            and not failed
        ):
            failed = True
            raise OSError("simulated active pointer fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(backup_service, "_fsync_directory", fail_after_pointer_switch)

    with pytest.raises(OSError, match="simulated active pointer fsync failure"):
        BackupService(source_root).promote_restored_generation(
            generation,
            active_state_pointer=active_pointer,
            maintenance_stability_window_seconds=0,
        )

    assert failed is True
    assert active_pointer.resolve() == source_root.resolve()
    assert not journal.exists()


def test_restore_rolls_back_when_promotion_directory_sync_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    target = tmp_path / "restored"
    journal = target.parent / f".{target.name}.restore-promotion.json"
    real_fsync_directory = backup_service._fsync_directory
    failed = False

    def fail_after_target_rename(path: Path) -> None:
        nonlocal failed
        if path == target.parent and target.exists() and not failed:
            failed = True
            raise OSError("simulated promotion fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(backup_service, "_fsync_directory", fail_after_target_rename)

    with pytest.raises(OSError, match="simulated promotion fsync failure"):
        BackupService(source_root).restore_backup(
            archive,
            target_state_root=target,
            skip_pre_backup=True,
        )

    assert failed is True
    assert not target.exists()
    assert not journal.exists()
    assert not list(target.parent.glob(f".{target.name}.restore-*"))


def test_interrupted_multi_root_promotion_is_rolled_back_before_a_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale journal returns a partial publish to private candidates safely."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    source_workspace = tmp_path / "source-workspace"
    (source_workspace / "project").mkdir(parents=True)
    (source_workspace / "project" / "README.md").write_text("workspace", encoding="utf-8")
    archive = BackupService(source_root).create_backup(
        tmp_path / "archive.tar.gz",
        include_workspaces=True,
        workspace_root=source_workspace,
    )
    manifest = BackupService(source_root).verify_backup(archive)
    target = tmp_path / "restored"
    workspace_target = tmp_path / "restored-workspace"
    candidate = target.parent / f".{target.name}.restore-crashed"
    workspace_candidate = workspace_target.parent / f".{workspace_target.name}.restore-crashed"
    candidate.mkdir()
    workspace_candidate.mkdir()
    (candidate / "marker").write_text("state", encoding="utf-8")
    (workspace_candidate / "marker").write_text("workspace", encoding="utf-8")
    os_replace = backup_service.os.replace
    os_replace(candidate, target)

    journal = target.parent / f".{target.name}.restore-promotion.json"
    payload: dict[str, object] = {
        "version": backup_service._RESTORE_PROMOTION_JOURNAL_VERSION,
        "operation_id": "crashed-promotion",
        "manifest_digest": backup_service._manifest_digest(manifest),
        "hostname": "test-host",
        "process_id": 1,
        "phase": "promoting",
        "pairs": [
            {"candidate": str(candidate), "target": str(target), "status": "promoted"},
            {
                "candidate": str(workspace_candidate),
                "target": str(workspace_target),
                "status": "staged",
            },
        ],
    }
    backup_service._write_promotion_journal(journal, payload, exclusive=True)
    monkeypatch.setattr(backup_service, "_journal_process_is_alive", lambda _payload: False)

    assert (
        backup_service._recover_pending_restore_promotion(
            journal,
            expected_manifest_digest=backup_service._manifest_digest(manifest),
        )
        == "rolled_back"
    )
    assert not target.exists()
    assert not workspace_target.exists()
    assert not candidate.exists()
    assert not workspace_candidate.exists()
    assert not journal.exists()

    restored = BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        target_workspace_root=workspace_target,
        skip_pre_backup=True,
    )
    assert restored == target
    assert (target / "runtime" / "auth.sqlite3").exists()
    assert (workspace_target / "project" / "README.md").read_text(encoding="utf-8") == "workspace"


def test_completed_promotion_journal_is_finalized_after_process_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """All renamed candidates are a completed generation, never rolled back."""

    source_root = tmp_path / "source"
    _seed_state(source_root)
    archive = BackupService(source_root).create_backup(tmp_path / "archive.tar.gz")
    manifest = BackupService(source_root).verify_backup(archive)
    target = tmp_path / "restored"
    candidate = target.parent / f".{target.name}.restore-crashed"
    candidate.mkdir()
    (candidate / "completed-marker").write_text("complete", encoding="utf-8")
    backup_service.os.replace(candidate, target)
    journal = target.parent / f".{target.name}.restore-promotion.json"
    payload: dict[str, object] = {
        "version": backup_service._RESTORE_PROMOTION_JOURNAL_VERSION,
        "operation_id": "completed-promotion",
        "manifest_digest": backup_service._manifest_digest(manifest),
        "hostname": "test-host",
        "process_id": 1,
        "phase": "completed",
        "pairs": [{"candidate": str(candidate), "target": str(target), "status": "promoted"}],
    }
    backup_service._write_promotion_journal(journal, payload, exclusive=True)
    monkeypatch.setattr(backup_service, "_journal_process_is_alive", lambda _payload: False)

    restored = BackupService(source_root).restore_backup(
        archive,
        target_state_root=target,
        skip_pre_backup=True,
    )

    assert restored == target
    assert (target / "completed-marker").read_text(encoding="utf-8") == "complete"
    assert not journal.exists()
