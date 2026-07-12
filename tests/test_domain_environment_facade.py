"""Persistent Environment facade coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain import DomainService, PersistentEnvironmentFacade

pytestmark = [pytest.mark.unit]


def test_persistent_environment_facade_survives_restart_without_detection_side_effects(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
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
    assert [item.id for item in second] == [environment_id]

    service.disable_environment(environment_id, {"id": "admin", "role": "admin"})

    assert PersistentEnvironmentFacade(state_root).list_environments() == []
    assert (
        PersistentEnvironmentFacade(state_root).get_environment(environment_id).display_name
        == "Durable host"
    )
