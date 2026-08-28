"""Persistent Environment facade coverage."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from ainrf.db import connect
from ainrf.domain import PersistentEnvironmentFacade, build_domain_modules
from ainrf.environments.models import EnvironmentAuthKind

pytestmark = [pytest.mark.unit]


def test_persistent_environment_facade_survives_restart_without_detection_side_effects(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    service = build_domain_modules(state_root, artifact_sha=committed_v2_state).environments
    environment = service.create_environment(
        {"id": "admin", "role": "admin"},
        alias="durable-host",
        display_name="Durable host",
        connection={
            "host": "compute.example",
            "port": 2202,
            "user": "researcher",
            "auth_kind": "ssh_key",
            "identity_file": "/keys/researcher",
            "tags": ["gpu", "research"],
            "ssh_options": {"StrictHostKeyChecking": "yes"},
        },
    )
    environment_id = str(environment["environment_id"])

    first = PersistentEnvironmentFacade(state_root).get_environment(environment_id)
    second = PersistentEnvironmentFacade(state_root).list_environments()

    assert first.host == "compute.example"
    assert first.port == 2202
    assert first.user == "researcher"
    assert first.tags == ["gpu", "research"]
    assert environment_id in [item.id for item in second]

    service.disable_environment(environment_id, {"id": "admin", "role": "admin"})

    assert environment_id not in [
        item.id for item in PersistentEnvironmentFacade(state_root).list_environments()
    ]
    assert (
        PersistentEnvironmentFacade(state_root).get_environment(environment_id).display_name
        == "Durable host"
    )


def test_facade_falls_back_to_builtin_seed_connection_when_seed_row_has_none(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    _ = committed_v2_state
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE environments SET connection_json = '{}' WHERE environment_id = 'env-localhost'"
        )
        conn.commit()

    environment = PersistentEnvironmentFacade(state_root).get_environment("env-localhost")

    assert environment.host == "127.0.0.1"
    assert environment.port == 2222
    assert environment.auth_kind == EnvironmentAuthKind.SSH_KEY
    assert environment.identity_file == "/opt/ainrf/.ssh/ainrf_local"
    assert environment.user


def test_facade_keeps_explicit_seed_connection_over_builtin_fallback(
    state_root: Path,
    committed_v2_state: str,
) -> None:
    _ = committed_v2_state
    with closing(connect(state_root / "runtime" / "agentic_researcher.sqlite3")) as conn:
        conn.execute(
            "UPDATE environments SET connection_json = ? WHERE environment_id = 'env-localhost'",
            (json.dumps({"host": "seed-host.example", "port": 2202, "user": "researcher"}),),
        )
        conn.commit()

    environment = PersistentEnvironmentFacade(state_root).get_environment("env-localhost")

    assert environment.host == "seed-host.example"
    assert environment.port == 2202
    assert environment.user == "researcher"
