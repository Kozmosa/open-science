"""V2 Project/Workspace/Environment service and permission tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain.service import DomainPermissionError, DomainService

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def _admin() -> dict[str, object]:
    return {"id": "admin", "role": "admin"}


def _user(user_id: str) -> dict[str, object]:
    return {"id": user_id, "role": "member"}


def test_project_workspace_link_is_idempotent_and_does_not_grant_workspace_access(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
    admin = _admin()
    alice = _user("alice")
    bob = _user("bob")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={"host": "example"}
    )
    project = service.create_project(alice, name="Alice project")
    workspace = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/alice",
        label="Alice",
    )

    first = service.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        alice,
        idempotency_key="attach-1",
    )
    second = service.attach_workspace(
        str(project["project_id"]),
        str(workspace["workspace_id"]),
        alice,
        idempotency_key="attach-1",
    )

    assert first == second
    with pytest.raises(DomainPermissionError):
        service.attach_workspace(
            str(project["project_id"]),
            str(workspace["workspace_id"]),
            bob,
            idempotency_key="attach-2",
        )
    with pytest.raises(DomainPermissionError):
        service.attach_workspace(
            str(project["project_id"]),
            str(workspace["workspace_id"]),
            admin,
            idempotency_key="attach-3",
        )


def test_primary_replacement_and_detach_guard(state_root: Path) -> None:
    service = DomainService(state_root)
    admin, alice = _admin(), _user("alice")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    project = service.create_project(alice, name="Project")
    one = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/one",
        label="one",
    )
    two = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/two",
        label="two",
    )
    service.set_primary_workspace(
        str(project["project_id"]), str(one["workspace_id"]), alice, idempotency_key="one"
    )
    service.set_primary_workspace(
        str(project["project_id"]), str(two["workspace_id"]), alice, idempotency_key="two"
    )
    with pytest.raises(ValueError):
        service.detach_workspace(
            str(project["project_id"]), str(two["workspace_id"]), alice, idempotency_key="detach"
        )


def test_environment_is_disabled_not_hard_deleted_and_secret_is_redacted(state_root: Path) -> None:
    service = DomainService(state_root)
    environment = service.create_environment(
        _admin(),
        alias="host-a",
        display_name="Host A",
        connection={},
        credential_ref="secret://profile",
    )
    service.disable_environment(str(environment["environment_id"]), _admin())
    returned = service.environment(str(environment["environment_id"]), _admin())
    assert returned["status"] == "disabled"
    assert "credential_ref" not in returned


def test_default_project_cannot_be_archived_and_workspace_can_be_unregistered(
    state_root: Path,
) -> None:
    service = DomainService(state_root)
    admin, alice = _admin(), _user("alice")
    default = service.create_project(alice, name="Default", is_default=True)
    with pytest.raises(ValueError):
        service.archive_project(str(default["project_id"]), alice, reason="test")
    environment = service.create_environment(
        admin, alias="host-a", display_name="Host A", connection={}
    )
    workspace = service.create_workspace(
        alice,
        environment_id=str(environment["environment_id"]),
        canonical_path="/tmp/unregister",
        label="unregister",
    )
    service.unregister_workspace(str(workspace["workspace_id"]), alice)
    assert service.workspace(str(workspace["workspace_id"]), alice)["status"] == "unregistered"
