"""Fail-closed Environment grant reads across SQLite main and WAL files."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.auth.service import AuthService
from ainrf.domain.environment_access import (
    active_environment_execution_grant,
    has_active_environment_execution_grant,
)

pytestmark = [pytest.mark.unit]


def _auth_path(state_root: Path) -> Path:
    return state_root / "runtime" / "auth.sqlite3"


def _open_wal_keeper(path: Path) -> sqlite3.Connection:
    keeper = sqlite3.connect(path)
    assert keeper.execute("PRAGMA journal_mode = WAL").fetchone()[0].lower() == "wal"
    return keeper


def test_active_and_revoked_grants_are_observed_from_the_current_wal(
    state_root: Path,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    path = _auth_path(state_root)
    keeper = _open_wal_keeper(path)
    try:
        auth.grant_environment(
            env_id="environment-wal",
            user_id="wal-user",
            max_tasks=2,
            granted_by="admin",
        )
        assert path.with_name(f"{path.name}-wal").is_file()
        grant = active_environment_execution_grant(
            path,
            environment_id="environment-wal",
            user_id="wal-user",
        )
        assert grant is not None and grant.max_concurrent_tasks == 2
        assert has_active_environment_execution_grant(
            path,
            environment_id="environment-wal",
            user_id="wal-user",
        )

        auth.revoke_environment("environment-wal", "wal-user", revoked_by="admin")
        assert not has_active_environment_execution_grant(
            path,
            environment_id="environment-wal",
            user_id="wal-user",
        )
    finally:
        keeper.close()


@pytest.mark.parametrize("replacement", [b"", b"SQLite format 3", b"not a sqlite database"])
def test_invalid_main_file_rejects_a_stale_valid_wal(
    state_root: Path,
    replacement: bytes,
) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    path = _auth_path(state_root)
    keeper = _open_wal_keeper(path)
    try:
        auth.grant_environment(
            env_id="environment-stale-wal",
            user_id="wal-user",
            max_tasks=None,
            granted_by="admin",
        )
        assert has_active_environment_execution_grant(
            path,
            environment_id="environment-stale-wal",
            user_id="wal-user",
        )
        path.write_bytes(replacement)
        assert not has_active_environment_execution_grant(
            path,
            environment_id="environment-stale-wal",
            user_id="wal-user",
        )
    finally:
        keeper.close()


def test_valid_sqlite_main_without_required_grant_schema_denies(
    state_root: Path,
) -> None:
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    path = runtime / "auth.sqlite3"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE environment_access (environment_id TEXT)")
        conn.commit()

    assert not has_active_environment_execution_grant(
        path,
        environment_id="environment-missing-schema",
        user_id="wal-user",
    )


def test_invalid_negative_capacity_denies_corrupt_grant(state_root: Path) -> None:
    auth = AuthService(state_root=state_root)
    auth.initialize()
    path = _auth_path(state_root)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """
            INSERT INTO environment_access (
                environment_id, user_id, max_concurrent_tasks,
                granted_by_user_id, granted_at, status
            ) VALUES ('environment-corrupt', 'user-corrupt', -1, 'admin', 'now', 'active')
            """
        )
        conn.commit()

    assert (
        active_environment_execution_grant(
            path,
            environment_id="environment-corrupt",
            user_id="user-corrupt",
        )
        is None
    )
